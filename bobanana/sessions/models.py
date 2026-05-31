"""Chat session data models."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class SessionStatus(str, Enum):
    idle = "idle"
    running = "running"
    interrupted = "interrupted"
    done = "done"


@dataclass
class ChatSession:
    id: str
    title: str
    workspace: Path
    status: SessionStatus = SessionStatus.idle
    thread_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    token_input: int = 0
    token_output: int = 0

    @staticmethod
    def new(title: str, workspace: Path) -> "ChatSession":
        short = uuid.uuid4().hex[:8]
        return ChatSession(
            id=short,
            title=title or f"chat-{short}",
            workspace=workspace.resolve(),
        )

    def touch(self) -> None:
        self.updated_at = time.time()

    def to_meta(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "workspace": str(self.workspace),
            "status": self.status.value,
            "thread_id": self.thread_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "token_input": self.token_input,
            "token_output": self.token_output,
        }

    @classmethod
    def from_meta(cls, data: dict) -> "ChatSession":
        return cls(
            id=data["id"],
            title=data.get("title", data["id"]),
            workspace=Path(data["workspace"]).resolve(),
            status=SessionStatus(data.get("status", "idle")),
            thread_id=data.get("thread_id", uuid.uuid4().hex),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            token_input=int(data.get("token_input", 0)),
            token_output=int(data.get("token_output", 0)),
        )
