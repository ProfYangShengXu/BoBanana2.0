"""Executor agent — ReAct tool loop for a single plan step (no hard tool-iter cap in 3.0)."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Callable, List

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from ..logging_setup import get_logger
from ..state import ReviewResult
from ..tools.shell_tools import shell_environment_hint

log = get_logger("executor")


def _invoke_tool(tool, args: dict):
    try:
        return tool.invoke(args)
    except NotImplementedError:
        return asyncio.run(tool.ainvoke(args))


def _is_nonproductive(tool_name: str, args: dict, result: str) -> bool:
    r = str(result).lstrip()
    if r.startswith("Step stopped"):
        return True
    if r.startswith("ERROR"):
        return True
    if r.startswith("[cached]"):
        body = r.split("\n", 1)[-1].strip()
        if tool_name in ("read_file", "list_dir") and len(body) > 30 and not body.startswith("ERROR"):
            return False
        return True
    path = args.get("path")
    if isinstance(path, str) and not path.strip():
        return True
    return False


def tool_call_signature(name: str, args: dict) -> str:
    try:
        return f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
    except TypeError:
        return f"{name}:{args!s}"


SYSTEM = """You are the EXECUTOR for a terminal coding agent.
Accomplish the CURRENT STEP only, using the available tools (read_file, \
write_file, list_dir, run_shell). Think step-by-step, call tools as needed, and \
when the step is complete reply with a concise summary of what you did and the \
key result. Write real, working code — no placeholders or TODO stubs.

Shell guidance: every run_shell command must be valid for THIS host shell \
(see below). Keep commands simple and single-purpose; avoid long pipelines and \
shell-specific tricks. If a command fails, read the error and adapt rather than \
repeating it.

**Hard rule — no shell for directory exploration**: NEVER use run_shell for \
`dir`, `ls`, `find`, `cat`, `type`, or similar to list or read files. Use \
`list_dir` and `read_file` instead. For steps about listing or scanning paths, \
your first tool call must be `list_dir` or `read_file`, not `run_shell`.

**Report deliverable steps**: start with build_report_header (Agent must be BoBanana x.y.z from version_line); \
FIRST run_shell on this step MUST be pytest --collect-only -q — write_file on deliverable blocked until then; \
do NOT read_file deliverable or docs/delivery/output/*.md; no fabricated ``` code blocks; \
use fetch_url for external URLs.

Host environment: {shell_env}"""

_EV_WRITE_CHARS = 600
_EV_SHELL_CHARS = 800
_EV_TOTAL_CHARS = 3000


class ExecutorAgent:
    def __init__(self, llm, tools, max_tool_iters: int = 8,
                 on_tool: Callable[[str, dict, str], None] | None = None,
                 step_timeout: int = 600,
                 repeat_threshold: int = 3) -> None:
        self._llm = llm.bind_tools(tools)
        self._tools = {t.name: t for t in tools}
        self.max_tool_iters = max_tool_iters  # legacy; not used as hard cap in 3.0
        self._on_tool = on_tool
        self.step_timeout = step_timeout
        self.repeat_threshold = repeat_threshold
        self.last_evidence: str = ""

    @staticmethod
    def _evidence_line(name: str, args: dict, result: str) -> str | None:
        if name == "write_file":
            path = str(args.get("path", "?"))
            content = str(args.get("content", ""))
            snippet = content[:_EV_WRITE_CHARS]
            more = "" if len(content) <= _EV_WRITE_CHARS else f"\n…(+{len(content) - _EV_WRITE_CHARS} chars)"
            return f"[wrote] {path} ({len(content)} chars):\n{snippet}{more}"
        if name == "read_file":
            path = str(args.get("path", "?"))
            body = str(result)
            if body.startswith("[cached]"):
                body = body.split("\n", 1)[-1] if "\n" in body else body
            snippet = body[:_EV_WRITE_CHARS]
            more = "" if len(body) <= _EV_WRITE_CHARS else f"\n…(+{len(body) - _EV_WRITE_CHARS} chars)"
            return f"[read] {path} ({len(body)} chars):\n{snippet}{more}"
        if name == "run_shell":
            cmd = str(args.get("command", "?"))[:200]
            out = str(result)[:_EV_SHELL_CHARS]
            more = "" if len(str(result)) <= _EV_SHELL_CHARS else "\n…(truncated)"
            return f"[ran] {cmd}\n  -> {out}{more}"
        return None

    def execute(self, step_description: str, context: str,
                review: ReviewResult | None = None, prior_output: str | None = None,
                lang_directive: str = "", key_directives: list[str] | None = None,
                extra_tool_iters: int = 0,
                sig_counts: dict[str, int] | None = None) -> str:
        evidence: List[str] = []
        self.last_evidence = ""
        sig_counts = sig_counts if sig_counts is not None else {}
        recent_trace: list[str] = []

        instruction = [
            f"CURRENT STEP:\n{step_description}",
            f"\nMemory context:\n{context}",
        ]
        if key_directives:
            instruction.append(
                "\nTASK-LEVEL KEY DIRECTIVES (the whole task is NOT done until ALL are "
                "satisfied with real, verifiable work — keep these in mind for this step):\n- "
                + "\n- ".join(key_directives)
            )
        if review is not None and prior_output is not None:
            instruction.append("\nYour previous attempt produced:\n" + prior_output)
            budget_exhausted = prior_output.lstrip().startswith("Step stopped")
            if budget_exhausted:
                instruction.append(
                    "\nIMPORTANT: the previous attempt did NOT fail on quality — it ran out of "
                    "tool iterations while exploring. Do NOT repeat that exploration. Relevant "
                    "files/dirs already explored are in the memory context above (results marked "
                    "[cached] are already known). This time, go DIRECTLY to the core action of "
                    "this step (write the file / run the build / produce the artifact) within the "
                    "first 1-2 tool calls. Avoid list_dir/read_file unless strictly required."
                )
            else:
                numbered = "\n".join(f"  {i}. {s}" for i, s in enumerate(review.suggestions, 1)) or "  (none)"
                instruction.append(
                    "\nThe reviewer REJECTED your work. You MUST address every point below; "
                    "treat them as a checklist and resolve each one:\n" + numbered
                    + (f"\nReviewer rationale: {review.rationale}" if review.rationale else "")
                    + "\nRules for this retry: (a) do NOT repeat tool calls that already failed or "
                    "returned cached/identical results; (b) change your approach rather than "
                    "retrying the same commands; (c) finish only after each checklist item is "
                    "genuinely satisfied with real work."
                )

        system = SYSTEM.format(shell_env=shell_environment_hint()) + lang_directive
        messages: List = [
            SystemMessage(content=system),
            HumanMessage(content="\n".join(instruction)),
        ]

        def _commit_evidence() -> None:
            joined = "\n".join(evidence)
            self.last_evidence = (joined[:_EV_TOTAL_CHARS] + "\n…(more evidence truncated)"
                                  if len(joined) > _EV_TOTAL_CHARS else joined)

        start = time.monotonic()
        attempts = 0
        max_attempts = 200  # safety fuse only

        while attempts < max_attempts:
            if self.step_timeout and self.step_timeout > 0:
                if time.monotonic() - start > self.step_timeout:
                    _commit_evidence()
                    return f"Step stopped: step wall-clock timeout ({self.step_timeout}s)."

            attempts += 1
            ai: AIMessage = self._llm.invoke(messages)
            messages.append(ai)
            tool_calls = getattr(ai, "tool_calls", None) or []
            if not tool_calls:
                log.debug("executor finished after %d attempt(s)", attempts)
                _commit_evidence()
                return ai.content if isinstance(ai.content, str) else str(ai.content)

            timeout_detail: str | None = None
            for call in tool_calls:
                name = call["name"]
                args = call.get("args", {}) or {}
                tool = self._tools.get(name)
                log.info("tool call: %s(%s)", name, ", ".join(f"{k}={str(v)[:60]}" for k, v in args.items()))
                if tool is None:
                    result = f"ERROR: unknown tool {name}"
                else:
                    try:
                        result = _invoke_tool(tool, args)
                    except Exception as exc:
                        log.error("tool %s raised: %s", name, exc)
                        result = f"ERROR running {name}: {exc}"
                result_str = str(result)
                sig = tool_call_signature(name, args)
                if not _is_nonproductive(name, args, result_str):
                    sig_counts[sig] = sig_counts.get(sig, 0) + 1
                    recent_trace.append(f"{sig} -> {result_str[:120]}")
                    if len(recent_trace) > 8:
                        recent_trace.pop(0)
                    if sig_counts[sig] >= self.repeat_threshold:
                        log.warning("repeat tool sig %s x%d — micro replan", sig, sig_counts[sig])
                        _commit_evidence()
                        trace = "\n".join(recent_trace)
                        return f"MICRO_REPLAN_NEEDED:{sig}\n{trace}"

                if name == "run_shell" and result_str.lstrip().startswith("ERROR: TIMEOUT"):
                    if timeout_detail is None:
                        timeout_detail = result_str.strip().splitlines()[0]
                if not _is_nonproductive(name, args, result_str):
                    line = self._evidence_line(name, args, result_str)
                    if line:
                        evidence.append(line)
                if self._on_tool:
                    self._on_tool(name, args, result_str)
                messages.append(ToolMessage(content=result_str, tool_call_id=call["id"]))

            if timeout_detail is not None:
                log.warning("executor hit shell timeout — requesting replan: %s", timeout_detail)
                _commit_evidence()
                return f"REPLAN_NEEDED: {timeout_detail}"

        _commit_evidence()
        return "Step stopped: safety attempt limit reached."
