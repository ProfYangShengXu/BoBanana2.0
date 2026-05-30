"""Reviewer agent — the critic in the variant-ReAct loops.

Reviews two kinds of artifacts:
1. the plan (before execution), and
2. content written during a step (after execution),
returning a structured :class:`ReviewResult` the main agent acts on.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from ..state import Plan, ReviewResult

PLAN_SYSTEM = """You are a strict PLAN REVIEWER for a coding agent.

You MUST verify (use the deterministic Plan validation block when provided):
1. Every file path in steps exists in the Live workspace index — no phantom paths \
(`src/`, `plan_executor.py`, `base_tool.py`, etc.).
2. Step count ≤8 (architecture/critique tasks ≤8).
3. Architecture tasks include `read_file docs/PROJECT.md` and a final `write_file` report step.
4. On revision: do NOT suggest adding steps unless removing obsolete ones first — \
no plan bloat.

If validation says ok=true and paths look sound, approve when score≥6. \
Otherwise list concrete fixes. Be decisive — do not ask for more detail when paths are wrong."""

ARTIFACT_SYSTEM = """You are a strict CODE/CONTENT REVIEWER for a coding agent.

Judge ONLY by the EVIDENCE block (actual files written and actual command \
outputs) — NOT by the executor's prose summary, which is an unverified claim. \
Rules:
- If the executor claims something (e.g. "wrote a working function") but the \
EVIDENCE does not show a corresponding file/output supporting it, do NOT approve.
- Reject placeholders, TODO/`pass`/stub bodies, empty or truncated-looking files, \
and code that obviously wouldn't run.
- If the step implies verification (build/test/run) and no command output in the \
evidence shows it succeeding, treat it as unverified and do NOT approve unless the \
step was purely about writing a small, self-evident file.
- Approve only when the evidence genuinely shows the step's intent met with real, \
working content. Give concrete, actionable fixes when rejecting.
If the EVIDENCE block is empty, the step produced no verifiable artifact — approve \
only for steps that legitimately need no file/command (e.g. a pure analysis/answer \
step), otherwise reject and ask for the concrete artifact.
For **read-only analysis steps** (step text says read/analyze/review, not write/create): \
if EVIDENCE contains `[read]` lines for the files the step asked for AND the summary \
is consistent, you MAY approve even without `[wrote]`.
For **deliverable steps** (write report, create file, fix code): `[wrote]` evidence is \
required — reading alone is insufficient.
For **architecture/critique report deliverables**: the Report validation (deterministic) \
block is authoritative — any violation means do NOT approve. If needs_web is set, require \
web_search evidence with URLs or removal of external claims before approval."""


class ReviewerAgent:
    def __init__(self, structured_llm, max_attempts: int = 3) -> None:
        self._llm = structured_llm
        self._max_attempts = max_attempts

    def _parse_review(self, result) -> ReviewResult | None:
        if isinstance(result, ReviewResult):
            return result
        if isinstance(result, dict):
            try:
                return ReviewResult(**result)
            except Exception:
                return None
        return None

    def _invoke_review(self, messages, fallback_context: str) -> ReviewResult:
        for _ in range(self._max_attempts):
            parsed = self._parse_review(self._llm.invoke(messages))
            if parsed is not None:
                return parsed
        return ReviewResult(
            approved=False,
            score=0,
            suggestions=["Reviewer could not produce a structured verdict; please retry the step."],
            rationale=f"Structured review failed after {self._max_attempts} attempt(s) ({fallback_context})",
        )

    def review_plan(
        self,
        user_request: str,
        plan: Plan,
        context: str,
        lang_directive: str = "",
        validation_report: str = "",
        validation_ok: bool | None = None,
    ) -> ReviewResult:
        val_block = ""
        if validation_report:
            val_block = f"\nPlan validation (deterministic):\n{validation_report}\n"
            if validation_ok is False:
                val_block += "validation_ok=false — do NOT approve until paths and step count are fixed.\n"
        content = (
            f"User request:\n{user_request}\n\n"
            f"Proposed plan:\n{plan.model_dump_json(indent=2)}\n\n"
            f"Memory context:\n{context}\n"
            f"{val_block}\n"
            "Review this plan. Set approved=true only if it is genuinely ready."
        )
        return self._invoke_review(
            [SystemMessage(content=PLAN_SYSTEM + lang_directive), HumanMessage(content=content)],
            "review_plan",
        )

    def review_artifact(
        self,
        step_description: str,
        produced: str,
        context: str,
        lang_directive: str = "",
        evidence: str = "",
        report_validation_report: str = "",
        report_validation_ok: bool | None = None,
    ) -> ReviewResult:
        evidence_block = evidence.strip() if evidence and evidence.strip() else "(no artifacts produced this step)"
        val_block = ""
        if report_validation_report:
            val_block = f"\nReport validation (deterministic):\n{report_validation_report}\n"
            if report_validation_ok is False:
                val_block += "report_validation_ok=false — do NOT approve until fixed.\n"
        content = (
            f"Current step:\n{step_description}\n\n"
            f"Executor's self-report (UNVERIFIED claim):\n{produced}\n\n"
            f"EVIDENCE — actual files written & command outputs (ground truth):\n{evidence_block}\n"
            f"{val_block}\n"
            f"Memory context:\n{context}\n\n"
            "Review per the rules. Set approved=true ONLY if the EVIDENCE supports that "
            "the step is genuinely done well."
        )
        return self._invoke_review(
            [SystemMessage(content=ARTIFACT_SYSTEM + lang_directive), HumanMessage(content=content)],
            "review_artifact",
        )
