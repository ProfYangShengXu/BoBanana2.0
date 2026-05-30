"""Directive gate — verifies the plan's key_directives before the task finishes.

After all steps complete, this critic checks whether every task-level hard
requirement (key_directives) is actually satisfied by the work done. If not, the
graph loops back to execute the remaining work instead of ending prematurely.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from ..state import DirectiveCheck

SYSTEM = """You are the DIRECTIVE GATE for a coding agent. You are given the \
task, its key_directives (hard requirements), and the work completed so far. \
Decide whether EVERY directive is genuinely satisfied by real, verifiable work \
(files actually written, commands actually run with output, etc.). \
Be strict: a step summary claiming success without evidence does NOT satisfy a \
directive. If anything is unmet, set all_satisfied=false and list each unmet \
directive as a concrete remaining action."""


class DirectiveGate:
    def __init__(self, structured_llm, max_attempts: int = 2) -> None:
        self._llm = structured_llm
        self._max_attempts = max_attempts

    def _parse(self, result) -> DirectiveCheck | None:
        if isinstance(result, DirectiveCheck):
            return result
        if isinstance(result, dict):
            try:
                return DirectiveCheck(**result)
            except Exception:
                return None
        return None

    def check(self, user_request: str, directives: list[str], completed: str,
              lang_directive: str = "") -> DirectiveCheck:
        if not directives:
            return DirectiveCheck(all_satisfied=True, unmet=[], notes="no key directives")
        content = (
            f"Task:\n{user_request}\n\n"
            f"Key directives (must ALL be satisfied):\n- " + "\n- ".join(directives) + "\n\n"
            f"Work completed so far:\n{completed}\n\n"
            "Decide if every directive is satisfied with real evidence."
        )
        messages = [SystemMessage(content=SYSTEM + lang_directive), HumanMessage(content=content)]
        for _ in range(self._max_attempts):
            parsed = self._parse(self._llm.invoke(messages))
            if parsed is not None:
                return parsed
        # Conservative fallback: if the gate can't produce a verdict, do NOT claim
        # success. Mark unverified so the task is reported as partial (unmet is left
        # empty so we don't trigger a pointless remediation loop on a flaky gate).
        return DirectiveCheck(
            all_satisfied=False,
            unmet=[],
            notes=f"directive gate could not verify key directives after {self._max_attempts} "
                  "attempt(s); reporting as unverified rather than assuming success",
        )
