"""LangGraph orchestration of the variant-ReAct workflow.

Flow:

    START
      -> plan            (main: planner produces/revises plan)
      -> plan_review     (critic: evaluate plan)
         | not approved & budget left -> plan        (revise)
         | else                       -> execute
      -> execute         (main: ReAct tool loop for current step)
      -> exec_review     (critic: evaluate produced work)
         | not approved & budget left -> execute      (revise)
         | else                       -> advance
      -> advance         (mark step done; more steps -> execute; else -> finalize)
      -> finalize        (summarize)  -> END
"""

from __future__ import annotations

import time
import uuid
from typing import Callable, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .agents import DirectiveGate, ExecutorAgent, PlannerAgent, ReviewerAgent
from .config import Settings
from .llm import wrap_structured_output
from .language import language_directive
from .logging_setup import get_logger
from .memory import MemoryManager
from .skills import SkillRegistry
from .state import AgentState, DirectiveCheck, Plan, PlanStep, ReviewResult, new_state
from .tools import Toolbox
from .triage import is_code_task, needs_agent_pipeline

EventCallback = Callable[[dict], None]
log = get_logger("graph")


class CodingAgentGraph:
    def __init__(self, settings: Settings, llm, memory: MemoryManager,
                 on_event: Optional[EventCallback] = None,
                 skill_registry: Optional[SkillRegistry] = None,
                 mcp_tools: Optional[list] = None,
                 delivery_gate_text: str = "",
                 models: Optional[dict] = None) -> None:
        self.settings = settings
        self.memory = memory
        self.on_event = on_event or (lambda e: None)
        self._gate_directive = self._build_gate_directive(delivery_gate_text)

        # Per-role temperature tiers. ``models`` maps role -> chat model; when not
        # supplied (e.g. offline tests) the single ``llm`` is used for every role.
        m = models or {}
        planner_llm = m.get("planner", llm)
        reviewer_llm = m.get("reviewer", llm)
        gate_llm = m.get("directive_gate", llm)
        executor_llm = m.get("executor", llm)
        self._finalize_llm = m.get("finalize", llm)

        # Checkpoint/interrupt runner state (set per run()).
        self._active_config: Optional[dict] = None
        self._interrupted: bool = False

        self.toolbox = Toolbox(
            settings.workspace, memory,
            shell_timeout=settings.shell_timeout,
            skill_registry=skill_registry,
            web_enabled=settings.enable_web_tools,
            mcp_tools=mcp_tools,
            exploration_cache=settings.enable_exploration_cache,
            plugin_dir=settings.plugin_dir,
            enable_plugins=settings.enable_tool_plugins,
            permission_policy=settings.permission_policy(),
        )
        log.info("toolbox ready with %d tool(s): %s", len(self.toolbox.tools),
                 ", ".join(getattr(t, "name", "?") for t in self.toolbox.tools))
        self.planner = PlannerAgent(wrap_structured_output(planner_llm, Plan, settings))
        self.reviewer = ReviewerAgent(wrap_structured_output(reviewer_llm, ReviewResult, settings))
        self.directive_gate = DirectiveGate(wrap_structured_output(gate_llm, DirectiveCheck, settings))
        self.executor = ExecutorAgent(
            executor_llm,
            self.toolbox.tools,
            max_tool_iters=settings.max_tool_iters,
            on_tool=self._emit_tool,
        )
        self._graph = self._build()

    # ----- event helpers -----
    def _emit(self, kind: str, **data) -> dict:
        event = {"kind": kind, **data}
        self.on_event(event)
        return event

    def _emit_tool(self, name: str, args: dict, result: str) -> None:
        from .report_validation import append_task_read_path, normalize_path

        r = str(result).lstrip()
        if name == "read_file" and not r.startswith("ERROR"):
            path = args.get("path")
            if isinstance(path, str) and path.strip():
                append_task_read_path(self.memory.working.scratch, path)
        elif name == "list_dir" and not r.startswith("ERROR"):
            path = args.get("path", ".")
            if isinstance(path, str):
                append_task_read_path(self.memory.working.scratch, normalize_path(path))
        self._emit("tool", name=name, args=args, result=result)

    # ----- context helper -----
    def _context_for(self, extra: str, user_request: str = "") -> str:
        from .workspace_map import inject_workspace_context
        base = self.memory.build_context(extra)
        if user_request:
            return inject_workspace_context(user_request, base, self.memory)
        return base

    def _workspace_index_text(self) -> str:
        return self.memory.working.get_scratch("workspace_index", "")

    def _lang(self, state: AgentState) -> str:
        return language_directive(state["user_request"])

    def _build_gate_directive(self, gate_text: str) -> str:
        """Condense the loaded code-delivery-gate SKILL.md into a system directive."""
        if not self.settings.enable_delivery_gate or not gate_text:
            return ""
        if gate_text.startswith("ERROR"):
            log.warning("delivery-gate skill not loaded: %s", gate_text)
            return ""
        excerpt = gate_text.strip()[:1800]
        log.info("delivery-gate skill loaded (%d chars) — active for code tasks", len(gate_text))
        return (
            "\n\n【交付门 / code-delivery-gate】此为代码任务，遵循以下交付质量门："
            "①写前锁定计划与逻辑链；②写后清理多余代码（死代码/未用 import/调试残留）；"
            "③交付前严肃自查逻辑链路（入口→校验→核心→副作用→失败/回滚），"
            "凡可由 agent 执行的步骤（安装/测试/构建/lint/健康检查）必须自行完成，不甩给用户。"
            "\n本机 skill 摘录：\n" + excerpt
        )

    def _directives(self, state: AgentState) -> str:
        """Language directive plus the delivery-gate directive for code tasks."""
        directive = self._lang(state)
        if self._gate_directive and needs_agent_pipeline(state["user_request"]):
            directive += self._gate_directive
        return directive

    # ----- nodes -----
    def _prepare_workspace_node(self, state: AgentState) -> dict:
        """Once per task: build live file index + tool catalog into scratch (no LLM)."""
        if self.memory.working.get_scratch("workspace_index"):
            log.debug("prepare_workspace: reusing cached scratch index")
            return {}
        from .workspace_index import build_workspace_index

        index = build_workspace_index(self.settings.workspace)
        self.memory.working.set_scratch("workspace_index", index)
        try:
            catalog = self.toolbox.describe_registry()
            self.memory.working.set_scratch("tool_catalog_summary", catalog[:1500])
        except Exception as exc:
            log.warning("tool catalog summary failed: %s", exc)
        log.info("prepare_workspace: index=%d chars, catalog in scratch", len(index))
        ev = self._emit("workspace_ready", index_chars=len(index))
        return {"events": [ev]}

    def _plan_node(self, state: AgentState) -> dict:
        log.info("node=plan revision=%d", state.get("plan_revisions", 0))
        prior = Plan(**state["plan"]) if state.get("plan") else None
        review = ReviewResult(**state["plan_review"]) if state.get("plan_review") else None
        context = self._context_for(state["user_request"], state["user_request"])
        directive = self._directives(state)
        val_errors = list(state.get("plan_validation_errors") or [])
        prior_steps = state.get("prior_plan_step_count", 0)
        plan = self.planner.plan(
            state["user_request"], context, prior, review, directive,
            validation_errors=val_errors,
            prior_step_count=prior_steps,
        )
        log.info("plan has %d step(s): %s", len(plan.steps), plan.summary)
        ev = self._emit("plan", plan=plan.model_dump(), revision=state.get("plan_revisions", 0))
        self.memory.record_fact("current_plan", plan.summary, category="plan")
        return {
            "plan": plan.model_dump(),
            "prior_plan_step_count": len(plan.steps),
            "events": [ev],
        }

    def _plan_review_node(self, state: AgentState) -> dict:
        from .plan_validation import validate_plan

        plan = Plan(**state["plan"])
        index_text = self._workspace_index_text()
        validation = validate_plan(
            plan, state["user_request"], self.settings.workspace, index_text,
        )
        context = self._context_for(state["user_request"], state["user_request"])
        review = self.reviewer.review_plan(
            state["user_request"], plan, context, self._lang(state),
            validation_report=validation.report(),
            validation_ok=validation.ok,
        )
        # Deterministic override: failed validation always blocks approval
        if not validation.ok or validation.phantom_hits:
            review = ReviewResult(
                approved=False,
                score=min(review.score, 4),
                suggestions=validation.error_messages() + list(review.suggestions),
                rationale=review.rationale or "Plan failed deterministic validation.",
            )
        log.info("node=plan_review approved=%s score=%d validation_ok=%s",
                 review.approved, review.score, validation.ok)
        ev = self._emit("plan_review", review=review.model_dump(), validation=validation.report())
        return {
            "plan_review": review.model_dump(),
            "plan_validation": {
                "ok": validation.ok,
                "phantom_hits": validation.phantom_hits,
                "unknown_paths": validation.unknown_paths,
                "step_count": validation.step_count,
            },
            "plan_validation_errors": validation.error_messages() if not validation.ok else [],
            "events": [ev],
        }

    def _route_after_plan_review(self, state: AgentState) -> str:
        review = ReviewResult(**state["plan_review"])
        val = state.get("plan_validation") or {}
        revs = state.get("plan_revisions", 0)
        if val.get("phantom_hits"):
            return "revise_plan"
        if review.approved:
            return "execute"
        if val.get("ok") and review.score >= 6 and revs >= 1:
            return "execute"
        if revs >= self.settings.max_plan_revisions:
            return "execute"
        return "revise_plan"

    def _revise_plan_node(self, state: AgentState) -> dict:
        prior_count = state.get("prior_plan_step_count", 0)
        return {
            "plan_revisions": state.get("plan_revisions", 0) + 1,
            "prior_plan_step_count": prior_count,
        }

    def _execute_node(self, state: AgentState) -> dict:
        from .report_validation import (
            begin_deliverable_write_step,
            build_report_header,
            extract_write_path,
            get_task_read_paths,
            is_report_deliverable_step,
        )

        plan = Plan(**state["plan"])
        idx = state.get("current_step", 0)
        step = plan.steps[idx]
        log.info("node=execute step=%d/%d rev=%d: %s", idx + 1, len(plan.steps),
                 state.get("exec_revisions", 0), step.description)
        review = ReviewResult(**state["exec_review"]) if state.get("exec_review") else None
        prior = state.get("step_output") or None
        extra_ctx = ""
        if is_report_deliverable_step(step.description):
            wp = extract_write_path(step.description)
            if wp:
                self.memory.working.set_scratch("deliverable_path", wp)
            begin_deliverable_write_step(
                self.memory.working.scratch,
                revision=state.get("exec_revisions", 0),
            )
            read_paths = get_task_read_paths(self.memory.working.scratch)
            extra_ctx = (
                "\n\nReport deliverable rules:\n"
                + build_report_header(read_paths)
                + "\nFIRST tool call on this step MUST be: pytest --collect-only -q (run_shell). "
                "write_file on the deliverable is blocked until pytest collect succeeds. "
                "Do NOT read_file deliverable or other docs/delivery/output/*.md. "
                "Use fetch_url for external package URLs.\n"
            )
        context = self._context_for(
            f"{state['user_request']}\nstep: {step.description}{extra_ctx}", state["user_request"],
        )
        ev_start = self._emit("step_start", index=idx + 1, total=len(plan.steps),
                              description=step.description)
        # Difficulty is a durable per-task floor on the per-step tool budget, so even
        # the FIRST attempt of a hard task gets more room; tool_iter_bonus is the
        # transient within-step retry bump (reset on advance). Take the larger.
        difficulty = state.get("difficulty", 0.5)
        difficulty_floor = round(difficulty * self.settings.max_tool_iters * 0.5)
        extra = max(state.get("tool_iter_bonus", 0), difficulty_floor)
        output = self.executor.execute(step.description, context, review, prior,
                                        self._directives(state), key_directives=plan.key_directives,
                                        extra_tool_iters=extra)
        # Don't let the replan sentinel leak into artifacts/memory once we can no
        # longer replan — turn it into an honest failure the reviewer can judge.
        if (output.lstrip().startswith("REPLAN_NEEDED")
                and state.get("plan_revisions", 0) >= self.settings.max_plan_revisions):
            detail = output.split("REPLAN_NEEDED:", 1)[-1].strip()
            output = ("Step stopped: a command timed out and the replan budget is "
                      f"exhausted. Unresolved: {detail}")
        ev = self._emit("step_output", index=idx + 1, output=output)
        return {"step_output": output, "events": [ev_start, ev]}

    def _route_after_execute(self, state: AgentState) -> str:
        """A shell timeout (REPLAN_NEEDED) reroutes to replan when budget allows;
        otherwise the step is reviewed normally (and will fail honestly)."""
        output = state.get("step_output", "") or ""
        if output.lstrip().startswith("REPLAN_NEEDED"):
            if state.get("plan_revisions", 0) < self.settings.max_plan_revisions:
                return "replan"
        return "exec_review"

    def _replan_node(self, state: AgentState) -> dict:
        """Triggered when a step's command timed out. Feed the timeout back to the
        planner as a revision request and restart execution from a fresh plan."""
        detail = (state.get("step_output", "") or "").replace("REPLAN_NEEDED:", "").strip()
        revs = state.get("plan_revisions", 0)
        log.warning("node=replan (shell timeout) revision=%d: %s", revs + 1, detail)
        synthetic = ReviewResult(
            approved=False,
            score=0,
            suggestions=[
                f"A command timed out: {detail}",
                "Avoid long-running/blocking commands; split work into smaller, "
                "bounded steps and prefer non-interactive flags.",
            ],
            rationale="Previous plan stalled on a shell timeout; revise the approach.",
        )
        difficulty = min(1.0, state.get("difficulty", 0.5) + 0.15)
        step_bonus = state.get("step_bonus", 0) + 2
        ev = self._emit("replan", detail=detail, revision=revs + 1)
        return {
            "plan_revisions": revs + 1,
            "plan_review": synthetic.model_dump(),
            "current_step": 0,
            "step_output": "",
            "exec_review": {},
            "exec_revisions": 0,
            "difficulty": difficulty,
            "step_bonus": step_bonus,
            "events": [ev],
        }

    def _exec_review_node(self, state: AgentState) -> dict:
        from .report_validation import (
            extract_write_path,
            get_task_read_paths,
            is_report_deliverable_step,
            validate_report_content,
        )

        plan = Plan(**state["plan"])
        idx = state.get("current_step", 0)
        step = plan.steps[idx]
        context = self._context_for(step.description, state["user_request"])
        evidence = getattr(self.executor, "last_evidence", "")
        report_val_report = ""
        report_val_ok: bool | None = None
        rv = None
        scratch = self.memory.working.scratch
        if is_report_deliverable_step(step.description):
            wp = extract_write_path(step.description)
            body = ""
            if wp:
                full = (self.settings.workspace / wp).resolve()
                if full.is_file():
                    try:
                        body = full.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        body = ""
            if not body and evidence:
                for line in evidence.splitlines():
                    if line.startswith("[wrote]"):
                        body = evidence
                        break
            if body:
                read_paths = get_task_read_paths(scratch)
                rv = validate_report_content(body, read_paths, self.settings.workspace, scratch=scratch)
                report_val_report = rv.report()
                report_val_ok = rv.ok
                if rv.needs_web and self.settings.enable_web_tools:
                    report_val_report += (
                        "\nAction: run web_search once for UNVERIFIED_EXTERNAL claims "
                        "and cite URLs, or remove those claims."
                    )
        review = self.reviewer.review_artifact(
            step.description, state.get("step_output", ""), context, self._directives(state),
            evidence=evidence,
            report_validation_report=report_val_report,
            report_validation_ok=report_val_ok,
        )
        if rv is not None and not rv.ok:
            suggestions = [report_val_report] + list(rv.violations) + list(review.suggestions)
            review = ReviewResult(
                approved=False,
                score=min(review.score, 4),
                suggestions=suggestions,
                rationale=review.rationale or "Report failed deterministic validation.",
            )
        log.info("node=exec_review step=%d approved=%s score=%d", idx + 1, review.approved, review.score)
        ev = self._emit("exec_review", index=idx + 1, review=review.model_dump())
        return {"exec_review": review.model_dump(), "events": [ev]}

    def _route_after_exec_review(self, state: AgentState) -> str:
        review = ReviewResult(**state["exec_review"])
        if review.approved or state.get("exec_revisions", 0) >= self.settings.max_exec_revisions:
            return "advance"
        return "revise_exec"

    def _revise_exec_node(self, state: AgentState) -> dict:
        # A rejected step is harder than estimated: ratchet difficulty up and grant
        # more per-step tool budget for the retry (bounded in the executor at 2x base).
        review = ReviewResult(**state["exec_review"]) if state.get("exec_review") else None
        score = review.score if review else 0
        bump = 0.2 if score < 4 else 0.1
        difficulty = min(1.0, state.get("difficulty", 0.5) + bump)
        bonus = state.get("tool_iter_bonus", 0) + max(2, round(self.settings.max_tool_iters * 0.5))
        ev = self._emit("difficulty", value=difficulty, tool_iter_bonus=bonus,
                        reason=f"step rejected (score={score})")
        return {
            "exec_revisions": state.get("exec_revisions", 0) + 1,
            "difficulty": difficulty,
            "tool_iter_bonus": bonus,
            "events": [ev],
        }

    def _advance_node(self, state: AgentState) -> dict:
        from .report_validation import (
            extract_write_path,
            get_task_read_paths,
            is_report_deliverable_step,
            validation_acceptable_ok,
            verify_deliverable_on_disk,
        )

        plan = Plan(**state["plan"])
        idx = state.get("current_step", 0)
        output = state.get("step_output", "")
        review = ReviewResult(**state["exec_review"]) if state.get("exec_review") else None
        step = plan.steps[idx]
        scratch = self.memory.working.scratch

        passed = review.approved if review is not None else True
        failed_steps = list(state.get("failed_steps", []))
        disk_verified = False

        if not passed and is_report_deliverable_step(step.description):
            wp = extract_write_path(step.description) or scratch.get("deliverable_path")
            if wp:
                read_paths = get_task_read_paths(scratch)
                _, _, validation = verify_deliverable_on_disk(
                    wp, self.settings.workspace, read_paths, scratch=scratch,
                )
                if validation_acceptable_ok(validation):
                    passed = True
                    disk_verified = True
                    log.info("step %d soft-pass: deliverable acceptable on disk at %s", idx + 1, wp)

        if passed and step.description.startswith("[补救"):
            dp = scratch.get("deliverable_path")
            if dp:
                read_paths = get_task_read_paths(scratch)
                _, _, validation = verify_deliverable_on_disk(
                    dp, self.settings.workspace, read_paths, scratch=scratch,
                )
                if validation_acceptable_ok(validation):
                    failed_steps = [
                        f for f in failed_steps
                        if not is_report_deliverable_step(f.get("description", ""))
                    ]

        if not passed:
            reason = (review.rationale if review and review.rationale
                      else "advanced without passing review (revision budget exhausted)")
            plan.steps[idx].result = f"[未通过审查/UNVERIFIED] {output}".strip()
            failed_steps.append({
                "id": plan.steps[idx].id,
                "description": plan.steps[idx].description,
                "score": review.score if review else 0,
                "reason": reason,
            })
            log.warning("step %d advanced WITHOUT passing review (score=%d): %s",
                        idx + 1, review.score if review else 0, plan.steps[idx].description)
        elif disk_verified:
            plan.steps[idx].result = f"[verified on disk] {output}".strip()
        else:
            plan.steps[idx].result = output
        plan.steps[idx].done = True
        self.memory.remember_turn("assistant", f"[step {idx + 1}] {output}")
        return {
            "plan": plan.model_dump(),
            "current_step": idx + 1,
            "exec_review": {},
            "exec_revisions": 0,
            "step_output": "",
            "failed_steps": failed_steps,
            "tool_iter_bonus": 0,
        }

    def _route_after_advance(self, state: AgentState) -> str:
        plan = Plan(**state["plan"])
        step_cap = self.settings.max_steps + state.get("step_bonus", 0)
        if state.get("current_step", 0) >= len(plan.steps) or state["current_step"] >= step_cap:
            return "directive_gate"
        return "execute"

    def _directive_gate_node(self, state: AgentState) -> dict:
        """After all steps run, verify every key_directive is actually satisfied.

        If not (and budget remains), append the unmet directives as new steps and
        loop back to execute, so the task does not end with directives unmet."""
        from .report_validation import (
            deliverable_disk_evidence_block,
            get_task_read_paths,
            remediable_validation_notes,
            resolve_deliverable_path,
            validation_acceptable_ok,
            verify_deliverable_on_disk,
        )

        plan = Plan(**state["plan"])
        scratch = self.memory.working.scratch
        if not plan.key_directives:
            check = DirectiveCheck(all_satisfied=True, notes="no key directives")
            return {"directive_check": check.model_dump()}

        dp = resolve_deliverable_path(scratch, plan.steps)
        disk_block = ""
        disk_validation = None
        disk_body = ""
        if dp:
            read_paths = get_task_read_paths(scratch)
            _, disk_body, disk_validation = verify_deliverable_on_disk(
                dp, self.settings.workspace, read_paths, scratch=scratch,
            )
            disk_block = deliverable_disk_evidence_block(
                dp, self.settings.workspace, read_paths, scratch=scratch,
            )

        completed = "\n".join(
            f"- {s.description}: {(s.result or '').strip()[:300]}" for s in plan.steps if s.done
        ) or "(nothing completed)"
        if disk_block:
            completed = completed + "\n\n" + disk_block

        check = self.directive_gate.check(
            state["user_request"], plan.key_directives, completed, self._lang(state),
        )
        notes = check.notes or ""
        revs = state.get("directive_revisions", 0)

        if dp and disk_validation and validation_acceptable_ok(disk_validation):
            notes = (notes + "; deliverable validation acceptable on disk at " + dp).strip("; ")
            report_unmet = [
                u for u in check.unmet
                if any(k in u for k in ("报告", "report", "critique", "交付", "write_file", "validation"))
            ]
            if report_unmet:
                remaining = [u for u in check.unmet if u not in report_unmet]
                check = DirectiveCheck(all_satisfied=not remaining, unmet=remaining, notes=notes)
            else:
                check = DirectiveCheck(
                    all_satisfied=check.all_satisfied,
                    unmet=check.unmet,
                    notes=notes,
                )
        elif dp and disk_validation and not validation_acceptable_ok(disk_validation):
            remediable = remediable_validation_notes(disk_validation, disk_body, scratch)
            if remediable and revs < self.settings.max_directive_revisions:
                next_id = max((s.id for s in plan.steps), default=0)
                for i, item in enumerate(remediable, start=1):
                    plan.steps.append(
                        PlanStep(id=next_id + i, description=f"[补救/报告校验] {item}")
                    )
                ev = self._emit("directive_gate", check=check.model_dump(), revision=revs, remedial=len(remediable))
                return {
                    "plan": plan.model_dump(),
                    "directive_check": check.model_dump(),
                    "directive_loop": True,
                    "directive_revisions": revs + 1,
                    "exec_review": {},
                    "exec_revisions": 0,
                    "events": [ev],
                }
        log.info("node=directive_gate satisfied=%s unmet=%d rev=%d",
                 check.all_satisfied, len(check.unmet), revs)
        ev = self._emit("directive_gate", check=check.model_dump(), revision=revs)

        should_loop = (not check.all_satisfied and bool(check.unmet)
                       and revs < self.settings.max_directive_revisions)
        if not should_loop:
            return {"directive_check": check.model_dump(), "directive_loop": False, "events": [ev]}

        # Append unmet directives as remedial steps and loop back to execute.
        next_id = max((s.id for s in plan.steps), default=0)
        for i, item in enumerate(check.unmet, start=1):
            plan.steps.append(PlanStep(id=next_id + i, description=f"[补救/未满足重要指令] {item}"))
        return {
            "plan": plan.model_dump(),
            "directive_check": check.model_dump(),
            "directive_loop": True,
            "directive_revisions": revs + 1,
            "exec_review": {},
            "exec_revisions": 0,
            "events": [ev],
        }

    def _route_after_directive_gate(self, state: AgentState) -> str:
        return "execute" if state.get("directive_loop") else "finalize"

    def _finalize_node(self, state: AgentState) -> dict:
        from .report_validation import (
            deliverable_disk_evidence_block,
            get_task_read_paths,
            is_report_deliverable_step,
            resolve_deliverable_path,
            validation_acceptable_ok,
            verify_deliverable_on_disk,
        )

        plan = Plan(**state["plan"])
        done = [f"{s.id}. {s.description}\n   -> {(s.result or '').strip()[:400]}" for s in plan.steps if s.done]
        body = "\n".join(done)
        lang = self._lang(state)
        zh = "简体中文" in lang
        check = state.get("directive_check") or {}
        unmet = check.get("unmet") or []
        failed = list(state.get("failed_steps", []))
        scratch = self.memory.working.scratch
        read_paths = get_task_read_paths(scratch)
        wrote_evidence = getattr(self.executor, "last_evidence", "")[:1500]
        gate_unverified = (check.get("all_satisfied") is False and not unmet)

        dp = resolve_deliverable_path(scratch, plan.steps)
        disk_ground = ""
        deliverable_acceptable = False
        if dp:
            _, _, validation = verify_deliverable_on_disk(
                dp, self.settings.workspace, read_paths, scratch=scratch,
            )
            disk_ground = deliverable_disk_evidence_block(
                dp, self.settings.workspace, read_paths, scratch=scratch,
            )
            deliverable_acceptable = validation_acceptable_ok(validation)
            if deliverable_acceptable:
                failed = [f for f in failed if not is_report_deliverable_step(f.get("description", ""))]
                gate_unverified = False

        is_partial = bool(failed) or bool(unmet) or gate_unverified
        status = "partial" if is_partial else "completed"

        issues = ""
        if failed:
            label = "\n\n【未通过审查的步骤】\n- " if zh else "\n\nSteps that did NOT pass review:\n- "
            issues += label + "\n- ".join(f"#{f['id']} {f['description']} ({f['reason']})" for f in failed)
        if unmet:
            label = "\n\n【未满足的重要指令】\n- " if zh else "\n\nUNMET key directives:\n- "
            issues += label + "\n- ".join(unmet)
        if gate_unverified:
            issues += ("\n\n【重要指令未能自动验证，需人工确认】" if zh
                       else "\n\nKey directives could NOT be auto-verified; manual confirmation needed.")

        disk_hint = (
            " Use DELIVERABLE_ON_DISK as ground truth; ignore superseded failed_steps for "
            "deliverable steps already verified on disk."
        )
        if is_partial:
            finalize_system = (
                "Summarize the task outcome HONESTLY. The task is only PARTIALLY complete: "
                "some steps did not pass review and/or key directives are unmet or unverified. "
                "Do NOT claim success. Clearly state what was done, what failed, and the "
                "remaining work, based strictly on the provided issues."
                + disk_hint
                + " Do NOT invent dimension scores or star ratings — if the report file has scores, "
                "say 'see report file' instead of restating numbers." + lang
            )
        else:
            finalize_system = (
                "Summarize the completed task for the user, concisely."
                + disk_hint
                + " Do NOT invent dimension scores or star ratings unless quoting verbatim from "
                "the disk evidence; otherwise say 'see report file'." + lang
            )
        ground = disk_ground or wrote_evidence or "(none)"
        try:
            msg = self._finalize_llm.invoke([
                SystemMessage(content=finalize_system),
                HumanMessage(content=(
                    f"Request: {state['user_request']}\n\n"
                    f"Completed steps:\n{body}\n\n"
                    f"Paths read this task: {', '.join(read_paths[:20]) or '(none)'}\n\n"
                    f"Ground truth (disk / last evidence):\n{ground}"
                    f"{issues}"
                )),
            ])
            summary = msg.content if isinstance(msg.content, str) else str(msg.content)
        except Exception:
            if is_partial:
                head = "任务部分完成（存在未通过/未满足项）。\n\n" if zh else "Task PARTIALLY complete (unresolved items).\n\n"
            else:
                head = "任务已完成。\n\n" if zh else "Task finished.\n\n"
            summary = head + body + issues
        ev = self._emit("final", summary=summary, status=status)
        self.memory.remember_turn("assistant", summary)
        return {"final_answer": summary, "status": status, "done": True, "events": [ev]}

    # ----- build -----
    def _build(self):
        g = StateGraph(AgentState)
        g.add_node("prepare_workspace", self._prepare_workspace_node)
        g.add_node("plan", self._plan_node)
        g.add_node("plan_review", self._plan_review_node)
        g.add_node("revise_plan", self._revise_plan_node)
        g.add_node("execute", self._execute_node)
        g.add_node("replan", self._replan_node)
        g.add_node("exec_review", self._exec_review_node)
        g.add_node("revise_exec", self._revise_exec_node)
        g.add_node("advance", self._advance_node)
        g.add_node("directive_gate", self._directive_gate_node)
        g.add_node("finalize", self._finalize_node)

        g.add_edge(START, "prepare_workspace")
        g.add_edge("prepare_workspace", "plan")
        g.add_edge("plan", "plan_review")
        g.add_conditional_edges("plan_review", self._route_after_plan_review,
                                {"revise_plan": "revise_plan", "execute": "execute"})
        g.add_edge("revise_plan", "plan")
        g.add_conditional_edges("execute", self._route_after_execute,
                                {"replan": "replan", "exec_review": "exec_review"})
        g.add_edge("replan", "plan")
        g.add_conditional_edges("exec_review", self._route_after_exec_review,
                                {"revise_exec": "revise_exec", "advance": "advance"})
        g.add_edge("revise_exec", "execute")
        g.add_conditional_edges("advance", self._route_after_advance,
                                {"execute": "execute", "directive_gate": "directive_gate"})
        g.add_conditional_edges("directive_gate", self._route_after_directive_gate,
                                {"execute": "execute", "finalize": "finalize"})
        g.add_edge("finalize", END)
        if self.settings.enable_checkpoints:
            return g.compile(checkpointer=MemorySaver())
        return g.compile()

    # ----- public API -----
    def _recursion_limit(self) -> int:
        return ((self.settings.max_steps + 1) * (self.settings.max_exec_revisions + 2) * 3
                + (self.settings.max_directive_revisions + 1) * 12
                + (self.settings.max_plan_revisions + 1) * (self.settings.max_steps + 6)
                + 30)

    def _stream(self, graph_input, config: dict) -> AgentState:
        """Drive the graph node-by-node so we can enforce a wall-clock timeout and
        catch Ctrl-C between super-steps, leaving a resumable checkpoint behind."""
        deadline = (time.monotonic() + self.settings.task_timeout
                    if self.settings.task_timeout and self.settings.task_timeout > 0 else None)
        last: AgentState = {}
        try:
            for snapshot in self._graph.stream(graph_input, config=config, stream_mode="values"):
                last = snapshot
                if deadline is not None and time.monotonic() > deadline:
                    return self._mark_interrupted(last, "timeout")
        except KeyboardInterrupt:
            return self._mark_interrupted(last, "user")
        self._interrupted = False
        log.info("run complete: done=%s status=%s", last.get("done"), last.get("status"))
        return last

    def _mark_interrupted(self, last: AgentState, reason: str) -> AgentState:
        self._interrupted = True
        log.warning("run INTERRUPTED (%s) at step %s", reason, last.get("current_step", 0))
        ev = self._emit("interrupted", reason=reason, current_step=last.get("current_step", 0))
        out = dict(last)
        out["interrupted"] = True
        out["interrupt_reason"] = reason
        out["events"] = list(out.get("events", [])) + [ev]
        return out

    def run(self, user_request: str, difficulty: float = 0.5) -> AgentState:
        from .report_validation import reset_task_read_paths

        log.info("run: %s (difficulty=%.2f)", user_request, difficulty)
        reset_task_read_paths(self.memory.working.scratch)
        self.memory.remember_turn("user", user_request)
        state = new_state(user_request, difficulty=difficulty)
        thread_id = uuid.uuid4().hex
        self._active_config = {"configurable": {"thread_id": thread_id},
                               "recursion_limit": self._recursion_limit()}
        return self._stream(state, self._active_config)

    @property
    def interrupted(self) -> bool:
        return self._interrupted

    def resume(self) -> Optional[AgentState]:
        """Continue an interrupted run from its last checkpoint (None input)."""
        if not (self.settings.enable_checkpoints and self._active_config and self._interrupted):
            return None
        log.info("resume from last checkpoint")
        return self._stream(None, self._active_config)

    def checkpoints(self) -> list[dict]:
        """Summarize resumable checkpoints (most recent first) for rollback."""
        if not (self.settings.enable_checkpoints and self._active_config):
            return []
        out: list[dict] = []
        try:
            for st in self._graph.get_state_history(self._active_config):
                out.append({
                    "checkpoint_id": st.config.get("configurable", {}).get("checkpoint_id"),
                    "current_step": st.values.get("current_step", 0),
                    "next": list(st.next),
                    "difficulty": st.values.get("difficulty"),
                })
        except Exception as exc:
            log.warning("could not read checkpoint history: %s", exc)
        return out

    def rollback(self, checkpoint_id: str) -> Optional[AgentState]:
        """Fork from a past checkpoint and continue execution from there."""
        if not (self.settings.enable_checkpoints and self._active_config and checkpoint_id):
            return None
        cfg = {
            "configurable": {
                "thread_id": self._active_config["configurable"]["thread_id"],
                "checkpoint_id": checkpoint_id,
            },
            "recursion_limit": self._recursion_limit(),
        }
        log.info("rollback to checkpoint %s and resume", checkpoint_id)
        self._emit("rollback", checkpoint_id=checkpoint_id)
        result = self._stream(None, cfg)
        # Continue future resumes from the active (forked) thread head.
        self._active_config = {
            "configurable": {"thread_id": self._active_config["configurable"]["thread_id"]},
            "recursion_limit": self._recursion_limit(),
        }
        return result
