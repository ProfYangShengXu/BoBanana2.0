"""Token usage tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


@dataclass
class TokenTotals:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, inp: int, out: int) -> None:
        self.input_tokens += inp
        self.output_tokens += out


class TokenUsageTracker:
    """Process-wide + per-session token counters."""

    def __init__(self) -> None:
        self.global_totals = TokenTotals()
        self._session: dict[str, TokenTotals] = {}
        self._task: dict[str, TokenTotals] = {}

    def session_totals(self, session_id: str) -> TokenTotals:
        if session_id not in self._session:
            self._session[session_id] = TokenTotals()
        return self._session[session_id]

    def begin_task(self, session_id: str, task_key: str) -> None:
        self._task[f"{session_id}:{task_key}"] = TokenTotals()

    def task_totals(self, session_id: str, task_key: str) -> TokenTotals:
        return self._task.get(f"{session_id}:{task_key}", TokenTotals())

    def record(self, session_id: str | None, task_key: str | None,
               inp: int, out: int) -> dict:
        self.global_totals.add(inp, out)
        if session_id:
            self.session_totals(session_id).add(inp, out)
        if session_id and task_key:
            key = f"{session_id}:{task_key}"
            if key not in self._task:
                self._task[key] = TokenTotals()
            self._task[key].add(inp, out)
        return {"input": inp, "output": out, "total": inp + out}


class TokenUsageHandler(BaseCallbackHandler):
    def __init__(self, tracker: TokenUsageTracker, session_id: str | None = None,
                 task_key: str | None = None, on_usage: Any = None) -> None:
        self.tracker = tracker
        self.session_id = session_id
        self.task_key = task_key
        self.on_usage = on_usage

    def on_llm_end(self, response, **kwargs) -> None:
        inp = out = 0
        if hasattr(response, "llm_output") and response.llm_output:
            usage = response.llm_output.get("token_usage") or {}
            inp = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        if hasattr(response, "generations") and response.generations:
            for gen_list in response.generations:
                for gen in gen_list:
                    meta = getattr(gen, "message", None)
                    if meta is not None:
                        um = getattr(meta, "usage_metadata", None) or {}
                        inp = int(um.get("input_tokens") or inp)
                        out = int(um.get("output_tokens") or out)
        if inp or out:
            stats = self.tracker.record(self.session_id, self.task_key, inp, out)
            if self.on_usage:
                self.on_usage(stats)
