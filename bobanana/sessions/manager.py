"""Session registry: multiple chat windows with isolated memory and graphs."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

from langgraph.checkpoint.memory import MemorySaver

from ..config import Settings, resolve_data_dir
from ..graph import CodingAgentGraph
from ..logging_setup import get_logger
from ..memory import MemoryManager
from ..tasks import EventBuffer
from ..undo import TurnJournal
from .forgetting import hydrate_with_forgetting
from .models import ChatSession, SessionStatus
from .store import SessionStore

if TYPE_CHECKING:
    from ..app import Application

log = get_logger("sessions.manager")


def build_checkpointer(db_path: Path):
    """SqliteSaver when available, else in-process MemorySaver."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        return SqliteSaver(conn)
    except ImportError:
        log.warning("langgraph-checkpoint-sqlite not installed; using MemorySaver")
        return MemorySaver()


@dataclass
class SessionRuntime:
    session: ChatSession
    store: SessionStore
    memory: MemoryManager
    settings: Settings
    event_buffer: EventBuffer = field(default_factory=EventBuffer)
    turn_journal: TurnJournal = field(default_factory=lambda: TurnJournal(Path()))
    graph: Optional[CodingAgentGraph] = None
    applied_budget: Optional[dict] = None
    event_cursor: int = 0
    last_turn_id: str | None = None

    def __post_init__(self) -> None:
        if not hasattr(self.turn_journal, "undo_dir") or str(self.turn_journal.undo_dir) == ".":
            self.turn_journal = TurnJournal(self.store.undo_dir)


class SessionManager:
    def __init__(self, base_settings: Settings, app: "Application") -> None:
        self.base_settings = base_settings
        self.app = app
        self.sessions_root = (base_settings.data_dir / "sessions").resolve()
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        self._runtimes: dict[str, SessionRuntime] = {}
        self._focus_id: str | None = None
        self._load_persisted()

    def _load_persisted(self) -> None:
        for sid in SessionStore.list_session_ids(self.sessions_root):
            store = SessionStore(self.sessions_root, sid)
            meta = store.load_meta()
            if meta:
                self._attach_runtime(ChatSession.from_meta(meta), store, hydrate=True)
        if not self._runtimes:
            self.create("default")

    def create(self, title: str = "") -> ChatSession:
        ws = self.base_settings.workspace
        chat = ChatSession.new(title or f"chat-{len(self._runtimes) + 1}", ws)
        store = SessionStore(self.sessions_root, chat.id)
        store.save_meta(chat.to_meta())
        rt = self._attach_runtime(chat, store, hydrate=False)
        self._focus_id = chat.id
        return rt.session

    def _attach_runtime(self, chat: ChatSession, store: SessionStore,
                        *, hydrate: bool) -> SessionRuntime:
        data_dir = resolve_data_dir(chat.workspace)
        memory = MemoryManager(data_dir, workspace=chat.workspace, session_id=chat.id)
        settings = self.base_settings.model_copy(deep=True)
        settings.workspace = chat.workspace
        settings.data_dir = data_dir
        settings.mcp_config = chat.workspace / "mcp.json"
        rt = SessionRuntime(
            session=chat,
            store=store,
            memory=memory,
            settings=settings,
            turn_journal=TurnJournal(store.undo_dir),
        )
        if hydrate:
            turns = store.load_turns()
            hydrate_with_forgetting(
                memory, chat.id, turns,
                recent_turns=settings.session_recent_turns,
                char_budget=settings.session_char_budget,
                summary_threshold=settings.session_summary_threshold,
            )
        self._runtimes[chat.id] = rt
        return rt

    @property
    def focus_id(self) -> str | None:
        return self._focus_id

    @property
    def focus(self) -> SessionRuntime | None:
        if self._focus_id and self._focus_id in self._runtimes:
            return self._runtimes[self._focus_id]
        return next(iter(self._runtimes.values()), None)

    @property
    def focus_memory(self) -> MemoryManager:
        rt = self.focus
        if rt is None:
            raise RuntimeError("no active session")
        return rt.memory

    def list_sessions(self) -> list[ChatSession]:
        return [rt.session for rt in self._runtimes.values()]

    def get(self, session_id: str) -> SessionRuntime | None:
        return self._runtimes.get(session_id)

    def switch(self, session_id: str) -> ChatSession | None:
        if session_id not in self._runtimes:
            # try numeric index
            sessions = self.list_sessions()
            try:
                idx = int(session_id)
                if 0 <= idx < len(sessions):
                    session_id = sessions[idx].id
            except ValueError:
                return None
        if session_id not in self._runtimes:
            return None
        self._focus_id = session_id
        rt = self._runtimes[session_id]
        rt.event_cursor = len(rt.event_buffer.tail(9999))
        return rt.session

    def delete(self, session_id: str) -> bool:
        if session_id not in self._runtimes:
            return False
        rt = self._runtimes.pop(session_id)
        if rt.graph:
            rt.graph = None
        rt.memory.close()
        import shutil
        shutil.rmtree(rt.store.root, ignore_errors=True)
        if self._focus_id == session_id:
            self._focus_id = next(iter(self._runtimes), None)
        return True

    def rename_focus(self, title: str) -> None:
        rt = self.focus
        if rt is None:
            return
        rt.session.title = title.strip() or rt.session.title
        rt.session.touch()
        rt.store.save_meta(rt.session.to_meta())

    def save_session_meta(self, rt: SessionRuntime) -> None:
        rt.session.touch()
        rt.store.save_meta(rt.session.to_meta())

    def append_turn(self, rt: SessionRuntime, role: str, content: str) -> None:
        rt.store.append_turn(role, content)
        rt.memory.remember_turn(role, content)
        rt.session.touch()
        self.save_session_meta(rt)

    def ensure_graph(self, rt: SessionRuntime, on_event: Callable[[dict], None]) -> CodingAgentGraph:
        ws = rt.settings.workspace.resolve()
        stale = (
            rt.graph is not None
            and (rt.graph.memory is not rt.memory or rt.graph.settings.workspace.resolve() != ws)
        )
        if stale:
            rt.graph = None
        if rt.graph is None:
            models = self.app._ensure_role_models(rt)
            checkpointer = build_checkpointer(rt.store.checkpoints_path)
            rt.graph = CodingAgentGraph(
                rt.settings,
                models["planner"],
                rt.memory,
                on_event=on_event,
                skill_registry=self.app.skills,
                mcp_tools=self.app._mcp_tools,
                delivery_gate_text=self.app._delivery_gate_text(),
                models=models,
                checkpointer=checkpointer,
                token_handler=self.app._make_token_handler(rt.session.id),
                micro_planner_llm=models.get("planner"),
                turn_journal=rt.turn_journal,
            )
        else:
            rt.graph.on_event = on_event
        return rt.graph

    def apply_budget(self, rt: SessionRuntime, task_size: float, user_request: str = "") -> dict:
        scaled = rt.settings.scaled_budget(task_size)
        if task_size >= 0.5 and user_request:
            from ..plan_validation import _is_architecture_task
            if _is_architecture_task(user_request):
                scaled = dict(scaled)
                scaled["max_plan_revisions"] = min(scaled["max_plan_revisions"], 1)
        if scaled == rt.applied_budget:
            return scaled
        for name, value in scaled.items():
            setattr(rt.settings, name, value)
        rt.applied_budget = scaled
        rt.graph = None
        log.info("session %s budget scaled: %s", rt.session.id, scaled)
        return scaled

    def close_all(self) -> None:
        for rt in self._runtimes.values():
            rt.memory.close()
