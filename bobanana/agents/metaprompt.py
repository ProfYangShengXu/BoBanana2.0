"""Meta-prompting agent.

When a task looks large or under-specified, this agent either asks targeted
clarifying questions or rewrites the request into a clearer, more complete brief
the planner can act on.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from ..state import TaskTriage

SYSTEM = """You are a META-PROMPTER for a terminal coding agent.
Given a user's task, decide whether it is clear and complete enough to start.
- If it is genuinely ambiguous or missing critical detail, set needs_clarification=true \
and provide 2-4 specific, high-value clarifying questions. Do NOT ask trivial questions.
- Otherwise set needs_clarification=false and write a refined_request: a clearer, \
self-contained restatement that fills reasonable defaults and makes scope explicit.
Always fill 'assessment' with a one-line note on scope/complexity.
Keep questions and refined_request in the SAME language as the user's task."""


class MetaPrompter:
    def __init__(self, structured_llm, max_attempts: int = 2) -> None:
        self._llm = structured_llm
        self._max_attempts = max_attempts

    def _parse(self, result) -> TaskTriage | None:
        if isinstance(result, TaskTriage):
            return result
        if isinstance(result, dict):
            try:
                return TaskTriage(**result)
            except Exception:
                return None
        return None

    def triage(self, user_request: str, lang_directive: str = "") -> TaskTriage:
        content = (
            f"User task:\n{user_request}\n\n"
            "Assess clarity and scope. If clear enough, refine it; otherwise ask questions."
        )
        messages = [
            SystemMessage(content=SYSTEM + lang_directive),
            HumanMessage(content=content),
        ]
        for _ in range(self._max_attempts):
            parsed = self._parse(self._llm.invoke(messages))
            if parsed is not None:
                return parsed
        # Fallback: proceed without changes.
        return TaskTriage(
            needs_clarification=False,
            questions=[],
            refined_request=user_request,
            assessment="meta-prompter unavailable; proceeding with original request",
        )
