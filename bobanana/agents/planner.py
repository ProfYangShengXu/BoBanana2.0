"""Planner agent — the "main" agent in the planning loop.

Produces a structured :class:`Plan`, and revises it when the reviewer agent
returns suggestions (the variant-ReAct planning loop).
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from ..state import Plan, ReviewResult

SYSTEM = """You are the PLANNER for a terminal coding agent.
Break the user's programming request into a short, ordered list of concrete, \
executable steps. Each step should be doable with file read/write/list or shell \
commands. Prefer 3-8 focused steps. Do not write code here — only plan.
Use the provided memory context to avoid re-doing work and to stay consistent \
with existing files and decisions.

Also set key_directives: 2-5 task-level HARD requirements that must ALL be true \
before the task can be considered finished. Make them concrete and verifiable \
(e.g. "the target file is actually written to disk", "the build runs and its \
output is captured", "no placeholder/TODO left"). These are the must-do \
instructions for this planning round: finishing individual steps does NOT end \
the task until every directive is satisfied. Avoid vague directives.

The memory context includes a **Live workspace index** (real files on disk) and a \
**Workspace map** — every path in steps MUST appear in the Live index or map. \
Never invent `src/`, `plan_executor.py`, `base_tool.py`, or `package.json` roots. \
For tool questions, plan `describe_tool_registry` (not `dir .bobanana/tools`). \
For architecture/critique tasks: ≤8 steps, first step `read_file docs/PROJECT.md`, \
last step `write_file docs/delivery/output/YYYY-MM-DD-architecture-critique.md` (today's date)."""


class PlannerAgent:
    def __init__(self, structured_llm) -> None:
        self._llm = structured_llm

    def plan(
        self,
        user_request: str,
        context: str,
        prior_plan: Plan | None = None,
        review: ReviewResult | None = None,
        lang_directive: str = "",
        validation_errors: list[str] | None = None,
        prior_step_count: int = 0,
    ) -> Plan:
        parts = [f"User request:\n{user_request}", f"\nMemory context:\n{context}"]
        if validation_errors:
            parts.insert(
                1,
                "Fix these path/plan errors BEFORE adding detail:\n- "
                + "\n- ".join(validation_errors),
            )
        if prior_plan is not None and review is not None:
            parts.append("\nYour previous plan was:\n" + prior_plan.model_dump_json(indent=2))
            parts.append(
                "\nThe reviewer asked you to revise it. Suggestions:\n- "
                + "\n- ".join(review.suggestions)
                + f"\nReviewer rationale: {review.rationale}"
            )
            if prior_step_count and len(prior_plan.steps) > prior_step_count:
                parts.append(
                    f"\nDo NOT add more steps than before ({prior_step_count}); "
                    "fix paths and trim redundant steps."
                )
            parts.append("\nProduce an improved plan addressing every suggestion.")
        else:
            parts.append("\nProduce the initial plan.")

        system = SYSTEM + lang_directive
        messages = [SystemMessage(content=system), HumanMessage(content="\n".join(parts))]
        plan: Plan = self._llm.invoke(messages)
        for i, step in enumerate(plan.steps, start=1):
            step.id = i
        return plan
