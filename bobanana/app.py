"""Application wiring: settings -> sessions -> background tasks -> graph."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Callable, Optional

from .config import Settings, default_skill_dirs, resolve_data_dir
from .graph import CodingAgentGraph
from .llm import build_role_models
from .logging_setup import get_logger, setup_logging
from .mcp import McpManager
from .memory import MemoryManager
from .sessions import SessionManager
from .skills import SkillRegistry
from .state import AgentState
from .tasks import TaskRunner, WorkspaceWriteLock
from .telemetry import TokenUsageHandler, TokenUsageTracker


class Application:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.load()
        self.settings.ensure_dirs()
        setup_logging(self.settings.log_level)
        self.log = get_logger("app")

        self.skills = SkillRegistry(self.settings.skill_dirs, self.settings.external_dir)
        self.mcp = McpManager(self.settings.mcp_config)
        self._mcp_tools = self.mcp.load()[0]
        self.token_tracker = TokenUsageTracker()
        self._role_models_cache: dict[str, dict] = {}
        self._metaprompter = None
        self._intent_agent = None

        self.session_manager = SessionManager(self.settings, self)
        self.task_runner = TaskRunner(self, max_workers=self.settings.max_concurrent_tasks)

        # Back-compat: focus session graph helpers (tests / resume)
        self._applied_budget: Optional[dict] = None

    @property
    def _graph(self) -> Optional[CodingAgentGraph]:
        rt = self.session_manager.focus
        return rt.graph if rt else None

    def _ensure_graph(self, on_event: Callable[[dict], None]) -> CodingAgentGraph:
        rt = self.session_manager.focus
        if rt is None:
            raise RuntimeError("no session")
        return self.session_manager.ensure_graph(rt, self._event_router(rt, on_event))

    @property
    def memory(self) -> MemoryManager:
        rt = self.session_manager.focus
        if rt is None:
            raise RuntimeError("no active session")
        return rt.memory

    @property
    def _graph_compat(self) -> Optional[CodingAgentGraph]:
        rt = self.session_manager.focus
        return rt.graph if rt else None

    def _delivery_gate_text(self) -> str:
        if not self.settings.enable_delivery_gate:
            return ""
        text = self.skills.read(self.settings.delivery_gate_skill)
        if text.startswith("ERROR"):
            self.log.warning("delivery-gate skill '%s' not found", self.settings.delivery_gate_skill)
            return ""
        return text

    def _make_token_handler(self, session_id: str, task_key: str | None = None):
        def on_usage(stats: dict) -> None:
            rt = self.session_manager.get(session_id)
            if rt:
                rt.session.token_input += stats.get("input", 0)
                rt.session.token_output += stats.get("output", 0)
                self.session_manager.save_session_meta(rt)
        return TokenUsageHandler(
            self.token_tracker, session_id=session_id, task_key=task_key, on_usage=on_usage,
        )

    def _ensure_role_models(self, rt=None) -> dict:
        sid = rt.session.id if rt else "_global"
        if sid not in self._role_models_cache:
            s = rt.settings if rt else self.settings
            handler = self._make_token_handler(sid) if rt else None
            cbs = [handler] if handler else None
            self._role_models_cache[sid] = build_role_models(s, callbacks=cbs)
        return self._role_models_cache[sid]

    def _event_router(self, rt, on_event: Callable[[dict], None]):
        def wrapped(event: dict) -> None:
            rt.event_buffer.append(event)
            if self.session_manager.focus_id == rt.session.id:
                on_event(event)
        return wrapped

    def classify_intent(self, request: str, rt=None):
        from .agents.intent import IntentAgent
        from .language import language_directive
        from .llm import wrap_structured_output
        from .state import Intent

        models = self._ensure_role_models(rt)
        if self._intent_agent is None:
            self._intent_agent = IntentAgent(
                wrap_structured_output(models["intent"], Intent, rt.settings if rt else self.settings))
        return self._intent_agent.classify(request, language_directive(request))

    def apply_budget(self, task_size: float, user_request: str = "", rt=None) -> dict:
        if rt is None:
            rt = self.session_manager.focus
        if rt is None:
            return {}
        return self.session_manager.apply_budget(rt, task_size, user_request)

    def chat_reply(self, request: str, rt=None) -> str:
        from .language import language_directive
        from langchain_core.messages import HumanMessage, SystemMessage

        models = self._ensure_role_models(rt)
        system = ("You are BoBanana, a friendly terminal coding agent. Reply briefly "
                  "and naturally to this small-talk / greeting message."
                  + language_directive(request))
        msg = models["finalize"].invoke(
            [SystemMessage(content=system), HumanMessage(content=request)])
        return msg.content if isinstance(msg.content, str) else str(msg.content)

    def triage_task(self, request: str, rt=None):
        from .agents.metaprompt import MetaPrompter
        from .language import language_directive
        from .llm import wrap_structured_output
        from .state import TaskTriage

        models = self._ensure_role_models(rt)
        if self._metaprompter is None:
            self._metaprompter = MetaPrompter(
                wrap_structured_output(models["intent"], TaskTriage, rt.settings if rt else self.settings))
        return self._metaprompter.triage(request, language_directive(request))

    def submit_task(self, session_id: str, request: str, on_event: Callable[[dict], None],
                    difficulty: float = 0.5) -> None:
        rt = self.session_manager.get(session_id)
        if rt is None:
            raise RuntimeError(f"unknown session {session_id}")

        def worker() -> None:
            lock = WorkspaceWriteLock.acquire(str(rt.settings.workspace))
            try:
                rt.session.status = __import__(
                    "bobanana.sessions.models", fromlist=["SessionStatus"]).SessionStatus.running
                turn_id = uuid.uuid4().hex[:12]
                rt.last_turn_id = turn_id
                self.token_tracker.begin_task(session_id, turn_id)
                handler = self._make_token_handler(session_id, turn_id)
                self._role_models_cache.pop(session_id, None)

                def routed(ev: dict) -> None:
                    if ev.get("kind") == "token_usage":
                        pass
                    self._event_router(rt, on_event)(ev)

                graph = self.session_manager.ensure_graph(rt, routed)
                graph._turn_journal = rt.turn_journal
                if graph.toolbox:
                    graph.toolbox._turn_journal = rt.turn_journal

                rt.turn_journal.begin_turn(
                    turn_id, rt.memory, checkpoint_id=None, thread_id=rt.session.thread_id,
                )
                rt.store.append_turn("user", request)

                result = graph.run(request, difficulty=difficulty)
                rt.turn_journal.finalize_turn()

                from .sessions.models import SessionStatus
                if result and result.get("interrupted"):
                    rt.session.status = SessionStatus.interrupted
                else:
                    rt.session.status = SessionStatus.done
                    if result and result.get("final_answer"):
                        rt.store.append_turn("assistant", result["final_answer"])
                self.session_manager.save_session_meta(rt)
            except Exception as exc:
                self.log.exception("task failed session=%s: %s", session_id, exc)
                rt.event_buffer.append({"kind": "error", "message": str(exc)})
                from .sessions.models import SessionStatus
                rt.session.status = SessionStatus.idle
            finally:
                WorkspaceWriteLock.release(lock)

        self.task_runner.submit(session_id, worker)

    def run_task(self, request: str, on_event: Callable[[dict], None],
                 difficulty: float = 0.5) -> AgentState:
        """Synchronous run (tests / compat)."""
        rt = self.session_manager.focus
        if rt is None:
            raise RuntimeError("no session")
        graph = self.session_manager.ensure_graph(rt, self._event_router(rt, on_event))
        graph._turn_journal = rt.turn_journal
        if graph.toolbox:
            graph.toolbox._turn_journal = rt.turn_journal
        return graph.run(request, difficulty=difficulty)

    def resume_task(self, on_event: Callable[[dict], None],
                    session_id: str | None = None) -> Optional[AgentState]:
        rt = self.session_manager.get(session_id or self.session_manager.focus_id or "")
        if rt is None or rt.graph is None or not rt.graph.interrupted:
            return None
        rt.graph.on_event = self._event_router(rt, on_event)
        return rt.graph.resume()

    def list_checkpoints(self, session_id: str | None = None) -> list[dict]:
        rt = self.session_manager.get(session_id or self.session_manager.focus_id or "")
        if rt is None or rt.graph is None:
            return []
        return rt.graph.checkpoints()

    def rollback_task(self, checkpoint_id: str, on_event: Callable[[dict], None],
                      session_id: str | None = None) -> Optional[AgentState]:
        rt = self.session_manager.get(session_id or self.session_manager.focus_id or "")
        if rt is None or rt.graph is None:
            return None
        rt.graph.on_event = self._event_router(rt, on_event)
        return rt.graph.rollback(checkpoint_id)

    def undo_last_turn(self, session_id: str | None = None) -> str:
        rt = self.session_manager.get(session_id or self.session_manager.focus_id or "")
        if rt is None:
            return "ERROR: no session"
        if self.task_runner.is_running(rt.session.id):
            return "ERROR: task still running"
        snap = rt.turn_journal.load_last()
        if snap is None:
            return "ERROR: nothing to undo"
        rt.turn_journal.apply_undo(snap, rt.settings.workspace, rt.memory)
        rt.store.pop_last_turns(2)
        return f"OK: undone turn {snap.turn_id}"

    def load_agent_reach(self) -> str:
        self.log.info("loading Agent-Reach from %s", self.settings.agent_reach_repo)
        return self.skills.clone_repo(self.settings.agent_reach_repo, name="Agent-Reach")

    def _make_toolbox(self):
        from .tools import Toolbox
        rt = self.session_manager.focus
        return Toolbox(
            self.settings.workspace, self.memory,
            shell_timeout=self.settings.shell_timeout,
            skill_registry=self.skills,
            web_enabled=self.settings.enable_web_tools,
            mcp_tools=self._mcp_tools,
            exploration_cache=self.settings.enable_exploration_cache,
            plugin_dir=self.settings.plugin_dir,
            enable_plugins=self.settings.enable_tool_plugins,
            permission_policy=self.settings.permission_policy(),
            turn_journal=rt.turn_journal if rt else None,
        )

    def list_tools(self) -> list[dict]:
        return self._make_toolbox().catalog()

    def reload_tools(self) -> str:
        tb = self._make_toolbox()
        for rt in self.session_manager.list_sessions():
            r = self.session_manager.get(rt.id)
            if r:
                r.graph = None
        report = tb._plugin_loader.report if tb._plugin_loader else None
        loaded = len(report.loaded) if report else 0
        errors = len(report.errors) if report else 0
        return (f"OK: {len(tb.catalog())} tool(s); plugins loaded={loaded}, errors={errors}")

    def set_workspace(self, new_workspace: Path) -> str:
        new_workspace = Path(new_workspace).resolve()
        if not new_workspace.is_dir():
            return f"ERROR: not a directory: {new_workspace}"

        rt = self.session_manager.focus
        if rt is None:
            return "ERROR: no active session"

        self.log.info("switching workspace -> %s", new_workspace)
        rt.settings.workspace = new_workspace
        rt.settings.data_dir = resolve_data_dir(new_workspace)
        rt.settings.mcp_config = new_workspace / "mcp.json"
        rt.settings.skill_dirs = default_skill_dirs(new_workspace)
        rt.settings.ensure_dirs()
        rt.session.workspace = new_workspace

        rt.memory.close()
        rt.memory = MemoryManager(
            rt.settings.data_dir, workspace=new_workspace, session_id=rt.session.id,
        )
        rt.graph = None
        self.skills = SkillRegistry(rt.settings.skill_dirs, self.settings.external_dir)
        self.mcp = McpManager(rt.settings.mcp_config)
        self._mcp_tools = self.mcp.load()[0]
        self.session_manager.save_session_meta(rt)
        return (f"OK: workspace set to {new_workspace}\n"
                f"memory store: {rt.settings.data_dir}")

    def close(self) -> None:
        self.task_runner.shutdown()
        self.session_manager.close_all()

    def selfcheck(self) -> list[tuple[str, bool, str]]:
        results: list[tuple[str, bool, str]] = []

        def check(name: str, fn):
            try:
                detail = fn()
                results.append((name, True, detail or "ok"))
            except Exception as exc:
                results.append((name, False, f"{type(exc).__name__}: {exc}"))

        check("settings", lambda: f"sessions={len(self.session_manager.list_sessions())}")
        check("sessions", lambda: f"focus={self.session_manager.focus_id}")

        def mem_roundtrip() -> str:
            m = self.memory
            m.remember_turn("user", "selfcheck conversation about caching layers")
            recalled = m.recall_conversation("caching")
            assert "caching" in recalled
            return f"recall_len={len(recalled)}"

        check("memory", mem_roundtrip)
        check("skills", lambda: f"count={len(self.skills.list())}")
        check("mcp", lambda: self.mcp.status)

        def tools_roundtrip() -> str:
            tb = self._make_toolbox()
            wt = tb.get("write_file")
            rt = tb.get("read_file")
            rel = ".bobanana/selfcheck_tool.txt"
            wt.invoke({"path": rel, "content": "hello from selfcheck"})
            content = rt.invoke({"path": rel})
            return f"read_ok={'hello' in content}"

        check("tools", tools_roundtrip)

        def graph_assembly() -> str:
            if not self.settings.has_llm:
                return "skipped (no OPENAI_API_KEY)"
            rt = self.session_manager.focus
            self.session_manager.ensure_graph(rt, lambda e: None)
            return "graph compiled"

        check("graph", graph_assembly)
        return results
