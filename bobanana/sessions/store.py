"""Persistent session storage (meta, turns, checkpoints path)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from ..logging_setup import get_logger

log = get_logger("sessions.store")


class SessionStore:
    def __init__(self, root: Path, session_id: str) -> None:
        self.root = (root / session_id).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "undo").mkdir(exist_ok=True)

    @property
    def meta_path(self) -> Path:
        return self.root / "meta.json"

    @property
    def turns_path(self) -> Path:
        return self.root / "turns.jsonl"

    @property
    def checkpoints_path(self) -> Path:
        return self.root / "checkpoints.db"

    @property
    def undo_dir(self) -> Path:
        return self.root / "undo"

    def save_meta(self, meta: dict) -> None:
        self.meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_meta(self) -> dict | None:
        if not self.meta_path.exists():
            return None
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    def append_turn(self, role: str, content: str) -> None:
        line = json.dumps({"role": role, "content": content}, ensure_ascii=False)
        with self.turns_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def load_turns(self) -> list[dict]:
        if not self.turns_path.exists():
            return []
        out: list[dict] = []
        for line in self.turns_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def pop_last_turns(self, count: int = 2) -> list[dict]:
        turns = self.load_turns()
        if not turns:
            return []
        removed = turns[-count:] if len(turns) >= count else turns[:]
        kept = turns[: len(turns) - len(removed)]
        with self.turns_path.open("w", encoding="utf-8") as f:
            for t in kept:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
        return removed

    @staticmethod
    def list_session_ids(sessions_root: Path) -> Iterator[str]:
        if not sessions_root.exists():
            return
        for p in sorted(sessions_root.iterdir()):
            if p.is_dir() and (p / "meta.json").exists():
                yield p.name
