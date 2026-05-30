"""Intent agent.

A cheap first-pass classifier (one structured LLM call) that sizes an incoming
task and decides whether meta-prompting is worthwhile. The size drives dynamic
budget scaling; greetings short-circuit the whole planning pipeline.

Falls back to token-free heuristics (triage.py) when the LLM is unavailable or
returns an unparseable result, so the pipeline never hard-fails on this step.

LLM estimates are calibrated against heuristic floors so multi-step search/report
tasks are not starved at task_size≈0.15.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from ..state import Intent
from ..triage import (
    estimate_task_size,
    is_greeting,
    looks_large,
    looks_research_task,
    looks_unclear,
    needs_agent_pipeline,
    should_metaprompt,
)

SYSTEM = """You are the INTENT classifier for a terminal coding agent.
Read the user's message and return a structured judgment:

task_size (0.0-1.0) — use these anchors:
  0.00 = greeting / small talk only ("你好", "who are you")
  0.10 = simple factual question, no tools needed
  0.35 = one small change or a single-file tweak
  0.50 = normal feature, bugfix, or script (few files)
  0.62 = multi-step research: web/GitHub search, fetch API, parse, write a report
  0.75 = multi-file refactor or non-trivial integration
  0.90 = large project-wide change or many modules

is_code_task: true if it needs reading/writing files, running shell, web search,
fetch_url, clone_repo, or producing a deliverable (report/markdown/output).

needs_metaprompt: true ONLY if genuinely ambiguous or very large scope where
clarifying first would clearly help.

reason: one short line.

IMPORTANT calibration rules:
- Do NOT assign 0.10-0.20 to tasks that need web search, GitHub/API calls, curl,
  multiple tool steps, or writing output files — those are at least 0.55.
- "搜索…整理/报告/写入" or "search … top/ranking" → typically 0.60-0.70.
- When unsure between two bands, pick the HIGHER size (budget starvation is worse
  than a little extra headroom)."""


def _heuristic_intent(text: str) -> Intent:
    """Token-free fallback estimate when the LLM intent call is unavailable."""
    size = estimate_task_size(text)
    pipeline = needs_agent_pipeline(text)
    return Intent(
        task_size=size,
        is_code_task=pipeline,
        needs_metaprompt=should_metaprompt(text),
        reason="heuristic fallback (intent LLM unavailable)",
    )


def _calibrate_intent(parsed: Intent, user_request: str) -> Intent:
    """Raise under-estimates; align is_code_task with pipeline needs."""
    floor = estimate_task_size(user_request)
    if floor > parsed.task_size:
        parsed.task_size = floor
        suffix = f"raised to heuristic floor {floor:.2f}"
        parsed.reason = f"{parsed.reason}; {suffix}" if parsed.reason else suffix

    if needs_agent_pipeline(user_request):
        parsed.is_code_task = True

    if looks_research_task(user_request) and parsed.task_size < 0.55:
        parsed.task_size = max(parsed.task_size, 0.58)
        if "research floor" not in parsed.reason:
            parsed.reason = (parsed.reason + "; research/multi-step floor 0.58").strip("; ")

    if is_greeting(user_request):
        parsed.task_size = 0.0
        parsed.is_code_task = False
        parsed.needs_metaprompt = False

    if looks_large(user_request) and parsed.task_size < 0.7:
        parsed.task_size = max(parsed.task_size, 0.72)

    if looks_unclear(user_request):
        parsed.needs_metaprompt = True

    parsed.task_size = max(0.0, min(1.0, float(parsed.task_size)))
    return parsed


class IntentAgent:
    def __init__(self, structured_llm, max_attempts: int = 2) -> None:
        self._llm = structured_llm
        self._max_attempts = max_attempts

    def _parse(self, result) -> Intent | None:
        if isinstance(result, Intent):
            return result
        if isinstance(result, dict):
            try:
                return Intent(**result)
            except Exception:
                return None
        return None

    def classify(self, user_request: str, lang_directive: str = "") -> Intent:
        messages = [
            SystemMessage(content=SYSTEM + lang_directive),
            HumanMessage(content=f"User message:\n{user_request}"),
        ]
        for _ in range(self._max_attempts):
            try:
                parsed = self._parse(self._llm.invoke(messages))
            except Exception:
                parsed = None
            if parsed is not None:
                return _calibrate_intent(parsed, user_request)
        return _heuristic_intent(user_request)
