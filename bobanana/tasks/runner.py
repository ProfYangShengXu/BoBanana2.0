"""Background task execution and event buffering."""

from __future__ import annotations

import threading
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..logging_setup import get_logger

log = get_logger("tasks")


class EventBuffer:
    """Thread-safe event log per session."""

    def __init__(self, max_events: int = 500) -> None:
        self._events: deque[dict] = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._cursor = 0

    def append(self, event: dict) -> None:
        with self._lock:
            self._events.append(event)

    def drain_since(self, cursor: int) -> tuple[list[dict], int]:
        with self._lock:
            events = list(self._events)
            new = events[cursor:]
            return new, len(events)

    def tail(self, n: int = 50) -> list[dict]:
        with self._lock:
            return list(self._events)[-n:]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class WorkspaceWriteLock:
    """One writer at a time per workspace path string."""

    _locks: dict[str, threading.Lock] = {}
    _guard = threading.Lock()

    @classmethod
    def acquire(cls, workspace: str) -> threading.Lock:
        with cls._guard:
            if workspace not in cls._locks:
                cls._locks[workspace] = threading.Lock()
            lock = cls._locks[workspace]
        lock.acquire()
        return lock

    @classmethod
    def release(cls, lock: threading.Lock) -> None:
        lock.release()


@dataclass
class TaskHandle:
    session_id: str
    future: Future
    request: str


class TaskRunner:
    def __init__(self, app, max_workers: int = 3) -> None:
        self._app = app
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="bobanana")
        self._handles: dict[str, TaskHandle] = {}
        self._lock = threading.Lock()

    def submit(self, session_id: str, fn: Callable[[], None]) -> None:
        with self._lock:
            old = self._handles.get(session_id)
            if old and not old.future.done():
                raise RuntimeError(f"session {session_id} already has a running task")
            future = self._pool.submit(fn)
            self._handles[session_id] = TaskHandle(session_id, future, "")

    def is_running(self, session_id: str) -> bool:
        with self._lock:
            h = self._handles.get(session_id)
            return h is not None and not h.future.done()

    def kill(self, session_id: str) -> bool:
        with self._lock:
            h = self._handles.pop(session_id, None)
        if h is None:
            return False
        return h.future.cancel()

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
