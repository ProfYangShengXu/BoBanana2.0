"""Turn-level undo journal."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FileSnapshot:
    path: str
    existed: bool
    content: str | None  # None if did not exist before write


@dataclass
class TurnSnapshot:
    turn_id: str
    checkpoint_id: str | None = None
    thread_id: str | None = None
    files: list[FileSnapshot] = field(default_factory=list)
    memory_turn_count: int = 0
    scratch: dict[str, str] = field(default_factory=dict)
    structured_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "turn_id": self.turn_id,
            "checkpoint_id": self.checkpoint_id,
            "thread_id": self.thread_id,
            "files": [{"path": f.path, "existed": f.existed, "content": f.content} for f in self.files],
            "memory_turn_count": self.memory_turn_count,
            "scratch": self.scratch,
            "structured_keys": self.structured_keys,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TurnSnapshot":
        files = [
            FileSnapshot(path=f["path"], existed=f["existed"], content=f.get("content"))
            for f in data.get("files", [])
        ]
        return cls(
            turn_id=data["turn_id"],
            checkpoint_id=data.get("checkpoint_id"),
            thread_id=data.get("thread_id"),
            files=files,
            memory_turn_count=int(data.get("memory_turn_count", 0)),
            scratch=dict(data.get("scratch") or {}),
            structured_keys=list(data.get("structured_keys") or []),
        )


class TurnJournal:
    def __init__(self, undo_dir: Path) -> None:
        self.undo_dir = undo_dir
        self.undo_dir.mkdir(parents=True, exist_ok=True)
        self._current: TurnSnapshot | None = None
        self._structured_added: list[str] = []

    def begin_turn(self, turn_id: str, memory, checkpoint_id: str | None,
                   thread_id: str | None) -> TurnSnapshot:
        snap = TurnSnapshot(
            turn_id=turn_id,
            checkpoint_id=checkpoint_id,
            thread_id=thread_id,
            memory_turn_count=len(memory.working.recent(9999)),
            scratch=dict(memory.working.scratch),
        )
        self._current = snap
        self._structured_added = []
        return snap

    def record_file_before_write(self, path: str, workspace: Path, file_ops) -> None:
        if self._current is None:
            return
        full = (workspace / path).resolve()
        existed = full.is_file()
        content = None
        if existed:
            try:
                content = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""
        self._current.files.append(FileSnapshot(path=path, existed=existed, content=content))

    def record_structured_key(self, key: str) -> None:
        if key not in self._structured_added:
            self._structured_added.append(key)

    def finalize_turn(self) -> None:
        if self._current is None:
            return
        self._current.structured_keys = list(self._structured_added)
        path = self.undo_dir / f"{self._current.turn_id}.json"
        path.write_text(json.dumps(self._current.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        self._current = None
        self._structured_added = []

    def load_last(self) -> TurnSnapshot | None:
        files = sorted(self.undo_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if not files:
            return None
        data = json.loads(files[-1].read_text(encoding="utf-8"))
        return TurnSnapshot.from_dict(data)

    def apply_undo(self, snap: TurnSnapshot, workspace: Path, memory) -> None:
        for fs in reversed(snap.files):
            full = (workspace / fs.path).resolve()
            if fs.existed:
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_text(fs.content or "", encoding="utf-8")
            elif full.exists():
                full.unlink()
                parent = full.parent
                if parent != workspace and not any(parent.iterdir()):
                    try:
                        parent.rmdir()
                    except OSError:
                        pass
        for key in snap.structured_keys:
            memory.structured._conn.execute("DELETE FROM facts WHERE key=?", (key,))
            memory.structured._conn.execute("DELETE FROM files WHERE path=?", (key.replace("file:", ""),))
        memory.structured._conn.commit()
        memory.working.clear()
        for k, v in snap.scratch.items():
            memory.working.set_scratch(k, v)
        while len(memory.working.recent(9999)) > snap.memory_turn_count:
            memory.working._turns.pop()
        last = self.undo_dir / f"{snap.turn_id}.json"
        if last.exists():
            last.unlink()
