"""Unified facade over the memory layers.

Routing policy:
- Live conversation window + scratch -> working memory (immediate context, keyword recall).
- Files, code symbols, important facts, exploration cache -> structured memory (exact lookup).

The previous semantic vector layer (ChromaDB) was removed: for a single-user
terminal agent the working-memory window plus exact structured lookups cover the
useful cases, and the hashed-embedding store added cost and a misleading
relevance signal without real semantic value.
"""

from __future__ import annotations

import re
from pathlib import Path

from .structured_memory import StructuredMemory
from .working_memory import WorkingMemory


def _tokens(text: str) -> set[str]:
    """Cheap multilingual token set: latin words + individual CJK chars."""
    low = text.lower()
    latin = set(re.findall(r"[a-z0-9_]{2,}", low))
    cjk = set(re.findall(r"[\u4e00-\u9fff]", low))
    return latin | cjk


class MemoryManager:
    def __init__(self, data_dir: Path, workspace: Path | None = None) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir = data_dir.resolve()
        self.workspace: Path | None = workspace.resolve() if workspace else None
        self.working = WorkingMemory()
        self.structured = StructuredMemory(self.data_dir / "structured.db")
        if self.workspace is not None:
            self.working.set_scratch("workspace_root", str(self.workspace))

    # ----- conversation (working memory only) -----
    def remember_turn(self, role: str, content: str) -> None:
        self.working.add_turn(role, content)

    def recall_conversation(self, query: str, k: int = 4) -> str:
        """Keyword recall over the working-memory window (no embeddings).

        Ranks recent turns by token overlap with the query; falls back to the
        most recent turns when nothing overlaps.
        """
        turns = self.working.recent(9999)
        if not turns:
            return ""
        q = _tokens(query)
        scored = []
        for i, t in enumerate(turns):
            overlap = len(q & _tokens(t["content"])) if q else 0
            scored.append((overlap, i, t))
        # Prefer overlap, then recency. Keep only positive-overlap hits if any exist.
        has_overlap = any(s[0] > 0 for s in scored)
        if has_overlap:
            scored = [s for s in scored if s[0] > 0]
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        # Per-line cap is defensive; WorkingMemory.add_turn already truncates turns.
        lines = [f"[{t['role']}] {t['content'][:800]}" for _, _, t in scored[:k]]
        return "\n".join(lines)

    # ----- structured high-value memory -----
    def record_file(self, path: str, summary: str, lines: int) -> None:
        self.structured.upsert_file(path, summary, lines)

    def record_fact(self, key: str, value: str, category: str = "general") -> None:
        self.structured.set_fact(key, value, category)

    def record_symbol(self, path: str, symbol: str, kind: str, snippet: str) -> None:
        self.structured.add_symbol(path, symbol, kind, snippet)

    # ----- exploration cache -----
    def recall_exploration(self, key: str) -> str | None:
        return self.structured.get_exploration(key)

    def record_exploration(self, key: str, tool: str, args: str, result: str) -> None:
        self.structured.save_exploration(key, tool, args, result)

    def invalidate_exploration(self) -> int:
        return self.structured.clear_exploration()

    def clear_mind(self) -> dict:
        """Reset task-polluting memory; keep scratch index/catalog and tracked files."""
        turns = len(self.working.recent(9999))
        self.working.clear_turns()
        exploration = self.structured.clear_exploration()
        facts = self.structured.clear_facts_categories(("plan", "session", "task", "diagnostic"))
        return {"turns_cleared": turns, "exploration_cleared": exploration, "facts_cleared": facts}

    # ----- context assembly -----
    def build_context(self, query: str) -> str:
        """Compose a context block from working + structured memory for a query."""
        parts: list[str] = []

        window = self.working.render()
        if window:
            parts.append("### Working memory (recent)\n" + window)

        recalled = self.recall_conversation(query)
        if recalled:
            parts.append("### Relevant recent turns (keyword)\n" + recalled)

        files = self.structured.list_files()
        if files:
            file_lines = [f"- {r['path']} ({r['lines']} lines): {r['summary']}" for r in files[:20]]
            parts.append("### Tracked files (exact)\n" + "\n".join(file_lines))

        facts = self.structured.all_facts()
        if facts:
            fact_lines = [f"- [{cat}] {k} = {v}" for k, v, cat in facts[:20]]
            parts.append("### Known facts (exact)\n" + "\n".join(fact_lines))

        return "\n\n".join(parts) if parts else "(memory empty)"

    def summary(self) -> dict:
        return {
            "working_turns": len(self.working.recent(9999)),
            "tracked_files": len(self.structured.list_files()),
            "facts": len(self.structured.all_facts()),
        }

    def close(self) -> None:
        self.structured.close()
