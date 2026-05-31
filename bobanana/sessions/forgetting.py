"""Load conversation history with recent-window + summary forgetting."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..memory import MemoryManager


def rule_summarize(turns: list[dict], max_chars: int = 800) -> str:
    """Offline-safe summary: first user line + turn count."""
    if not turns:
        return ""
    users = [t["content"][:120] for t in turns if t.get("role") == "user"]
    head = users[0] if users else turns[0].get("content", "")[:120]
    return f"[Earlier session: {len(turns)} turns. First request: {head}…]"


def hydrate_with_forgetting(
    memory: "MemoryManager",
    session_id: str,
    turns: list[dict],
    *,
    recent_turns: int = 12,
    char_budget: int = 6000,
    summary_threshold: int = 20,
) -> dict:
    """Restore working memory from persisted turns with forgetting."""
    memory.working.clear_turns()
    if not turns:
        return {"loaded": 0, "summarized": 0}

    old = turns[:-recent_turns] if len(turns) > recent_turns else []
    recent = turns[-recent_turns:] if len(turns) > recent_turns else turns

    summarized = 0
    if len(turns) >= summary_threshold and old:
        summary = rule_summarize(old)
        memory.record_fact(f"session:{session_id}:summary", summary, category="session")
        summarized = len(old)

    loaded = 0
    for t in recent:
        memory.remember_turn(t.get("role", "user"), t.get("content", ""))
        loaded += 1

    # Trim if over budget
    while memory.working.recent(9999) and memory.working._size() > char_budget:
        memory.working._turns.popleft()

    return {"loaded": loaded, "summarized": summarized}
