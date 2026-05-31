"""Micro planner — short unreviewed plan patch when executor is stuck on repeated tools."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..logging_setup import get_logger
from ..state import Plan, PlanStep

log = get_logger("micro_planner")


class PlanPatch(BaseModel):
    """Local adjustment to the current step (and optional follow-ups)."""

    revised_step: str = Field(description="Replacement description for the current step.")
    extra_steps: list[str] = Field(
        default_factory=list,
        description="0-2 optional steps to insert after the current one.",
    )
    rationale: str = Field(default="", description="One-line reason for the pivot.")


SYSTEM = """You are a micro-planner for a coding agent stuck in a tool loop.
The executor repeated the same tool call 3+ times without progress.
Propose a SMALL local plan adjustment: rewrite the CURRENT step to use a different
approach, and optionally add at most 2 short follow-up steps.
Do NOT replan the entire task — only unblock this step."""


class MicroPlanner:
    def __init__(self, llm) -> None:
        self._llm = llm

    def patch(self, user_request: str, plan: Plan, step_idx: int,
              stuck_sig: str, recent_trace: str) -> Plan:
        step = plan.steps[step_idx]
        msg = self._llm.invoke([
            SystemMessage(content=SYSTEM),
            HumanMessage(content=(
                f"Task: {user_request}\n"
                f"Plan summary: {plan.summary}\n"
                f"Current step #{step.id}: {step.description}\n"
                f"Repeated tool signature: {stuck_sig}\n"
                f"Recent tool trace:\n{recent_trace}\n\n"
                "Return JSON with revised_step, extra_steps (0-2), rationale."
            )),
        ])
        text = msg.content if isinstance(msg.content, str) else str(msg.content)
        try:
            patch = PlanPatch.model_validate_json(text)
        except Exception:
            # Fallback: parse as plain text revision
            patch = PlanPatch(revised_step=text[:500] or step.description, rationale="fallback")

        plan.steps[step_idx].description = patch.revised_step
        next_id = max((s.id for s in plan.steps), default=0) + 1
        for i, desc in enumerate(patch.extra_steps[:2], start=0):
            plan.steps.insert(step_idx + 1 + i, PlanStep(id=next_id + i, description=desc))
        log.info("micro_planner patch: %s", patch.rationale)
        return plan
