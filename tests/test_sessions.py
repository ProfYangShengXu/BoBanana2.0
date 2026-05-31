"""Tests for multi-chat sessions (BoBanana 3.0)."""

import tempfile
from pathlib import Path

from bobanana.app import Application
from bobanana.config import Settings
from bobanana.memory import MemoryManager
from bobanana.sessions.forgetting import hydrate_with_forgetting, rule_summarize
from bobanana.sessions.manager import SessionManager
from bobanana.sessions.models import ChatSession
from bobanana.sessions.store import SessionStore
from bobanana.tasks import EventBuffer
from bobanana.telemetry.tokens import TokenUsageTracker
from bobanana.undo.journal import TurnJournal


def test_session_store_turns_roundtrip(tmp_path):
    store = SessionStore(tmp_path / "sessions", "abc123")
    store.append_turn("user", "hello")
    store.append_turn("assistant", "hi")
    turns = store.load_turns()
    assert len(turns) == 2
    removed = store.pop_last_turns(2)
    assert len(removed) == 2
    assert store.load_turns() == []


def test_hydrate_with_forgetting_summarizes_old(tmp_path):
    mem = MemoryManager(tmp_path / ".bobanana")
    turns = [{"role": "user", "content": f"msg {i}"} for i in range(25)]
    stats = hydrate_with_forgetting(
        mem, "s1", turns, recent_turns=5, summary_threshold=20,
    )
    assert stats["summarized"] == 20
    assert stats["loaded"] == 5
    assert mem.structured.get_fact("session:s1:summary") is not None


def test_rule_summarize():
    turns = [{"role": "user", "content": "build a login system"}] * 10
    s = rule_summarize(turns)
    assert "10 turns" in s


def test_event_buffer_drain():
    buf = EventBuffer()
    buf.append({"kind": "tool", "name": "read_file"})
    new, cur = buf.drain_since(0)
    assert len(new) == 1
    assert cur == 1
    new2, _ = buf.drain_since(cur)
    assert new2 == []


def test_token_tracker_accumulates():
    tr = TokenUsageTracker()
    tr.record("s1", "t1", 100, 50)
    tr.record("s1", "t1", 10, 5)
    assert tr.session_totals("s1").total == 165
    assert tr.global_totals.total == 165


def test_turn_journal_undo_file(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    rel = "test.txt"
    full = ws / rel
    full.write_text("after", encoding="utf-8")
    undo_dir = tmp_path / "undo"
    journal = TurnJournal(undo_dir)
    mem = MemoryManager(tmp_path / ".bobanana", workspace=ws)
    snap = journal.begin_turn("turn1", mem, None, None)
    journal.record_file_before_write(rel, ws, type("F", (), {
        "read_file": lambda self, p: full.read_text(encoding="utf-8"),
    })())
    # simulate pre-existed content "before"
    snap.files[0].content = "before"
    snap.files[0].existed = True
    journal.finalize_turn()
    loaded = journal.load_last()
    assert loaded is not None
    journal.apply_undo(loaded, ws, mem)
    assert full.read_text(encoding="utf-8") == "before"


def test_session_manager_create_and_switch(tmp_path):
    settings = Settings(workspace=tmp_path, data_dir=tmp_path / ".bobanana", api_key="")
    app = Application(settings)
    s1 = app.session_manager.focus.session.id
    s2 = app.session_manager.create("second").id
    assert s2 != s1
    assert app.session_manager.switch(s2) is not None
    assert app.session_manager.focus_id == s2
    app.close()


def test_tool_call_signature_repeat():
    from bobanana.agents.executor import tool_call_signature
    a = tool_call_signature("read_file", {"path": "x.py"})
    b = tool_call_signature("read_file", {"path": "x.py"})
    assert a == b


def test_executor_no_hard_cap_uses_step_timeout():
    from bobanana.agents.executor import ExecutorAgent

    class FakeLLM:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            from langchain_core.messages import AIMessage
            return AIMessage(content="done without tools")

    ex = ExecutorAgent(FakeLLM(), [], step_timeout=0)
    out = ex.execute("step", "ctx")
    assert "done" in out
