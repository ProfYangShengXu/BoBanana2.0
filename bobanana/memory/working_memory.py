"""Working / context memory.

Holds the live conversation window and the current-task scratchpad. Bounded by a
character budget so it never overflows the prompt context.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List


@dataclass
class WorkingMemory:
    char_budget: int = 6000
    per_turn_chars: int = 2000  # cap one turn so a giant blob can't dominate context
    _turns: Deque[Dict[str, str]] = field(default_factory=lambda: deque())
    scratch: Dict[str, str] = field(default_factory=dict)

    def add_turn(self, role: str, content: str) -> None:
        # Truncate oversized turns at the source so neither the window nor keyword
        # recall can pull an unbounded blob into the prompt.
        if len(content) > self.per_turn_chars:
            content = content[: self.per_turn_chars] + "\n…(truncated)"
        self._turns.append({"role": role, "content": content})
        self._trim()

    def set_scratch(self, key: str, value: str) -> None:
        self.scratch[key] = value

    def get_scratch(self, key: str, default: str = "") -> str:
        return self.scratch.get(key, default)

    def _trim(self) -> None:
        while self._turns and self._size() > self.char_budget:
            self._turns.popleft()

    def _size(self) -> int:
        return sum(len(t["content"]) for t in self._turns)

    def recent(self, limit: int = 12) -> List[Dict[str, str]]:
        return list(self._turns)[-limit:]

    def render(self, limit: int = 12) -> str:
        lines = []
        for t in self.recent(limit):
            lines.append(f"{t['role'].upper()}: {t['content']}")
        if self.scratch:
            lines.append("--- scratch ---")
            for k, v in self.scratch.items():
                lines.append(f"{k}: {v}")
        return "\n".join(lines)

    def clear_turns(self) -> None:
        """Clear conversation turns only; keep scratch (workspace index, etc.)."""
        self._turns.clear()

    def clear(self) -> None:
        self._turns.clear()
        self.scratch.clear()
