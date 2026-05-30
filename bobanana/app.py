"""Application wiring: settings -> logging -> memory -> skills/mcp -> llm -> graph.

Keeps the LLM lazy so ``--selfcheck`` can validate everything offline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from .config import Settings, default_skill_dirs, resolve_data_dir
from .graph import CodingAgentGraph
from .llm import build_chat_model, build_role_models
from .logging_setup import get_logger, setup_logging
from .mcp import McpManager
from .memory import MemoryManager
from .skills import SkillRegistry
from .state import AgentState


class Application:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.load()
        self.settings.ensure_dirs()
        setup_logging(self.settings.log_level)
        self.log = get_logger("app")

        self.memory = MemoryManager(
            self.settings.data_dir, workspace=self.settings.workspace)
        self.skills = SkillRegistry(self.settings.skill_dirs, self.settings.external_dir)
        self.mcp = McpManager(self.settings.mcp_config)
        self._mcp_tools = self.mcp.load()[0]
        self._graph: Optional[CodingAgentGraph] = None
        self._role_models: Optional[dict] = None
        self._metaprompter = None
        self._intent_agent = None
        self._applied_budget: Optional[dict] = None

    def _delivery_gate_text(self) -> str:
        """Load the local code-delivery-gate SKILL.md (empty string if disabled/missing)."""
        if not self.settings.enable_delivery_gate:
            return ""
        text = self.skills.read(self.settings.delivery_gate_skill)
        if text.startswith("ERROR"):
            self.log.warning("delivery-gate skill '%s' not found", self.settings.delivery_gate_skill)
            return ""
        return text

    def _ensure_role_models(self) -> dict:
        if self._role_models is None:
            self._role_models = build_role_models(self.settings)
        return self._role_models

    def _ensure_graph(self, on_event: Callable[[dict], None]) -> CodingAgentGraph:
        if self._graph is not None:
            ws = self.settings.workspace.resolve()
            stale = (
                self._graph.memory is not self.memory
                or self._graph.settings.workspace.resolve() != ws
            )
            if stale:
                self.log.warning(
                    "graph stale (memory or workspace changed); rebuilding toolbox/graph")
                self._graph = None
        if self._graph is None:
            models = self._ensure_role_models()
            self._graph = CodingAgentGraph(
                self.settings, models["planner"], self.memory, on_event=on_event,
                skill_registry=self.skills, mcp_tools=self._mcp_tools,
                delivery_gate_text=self._delivery_gate_text(),
                models=models,
            )
        else:
            self._graph.on_event = on_event
        return self._graph

    def classify_intent(self, request: str):
        """Intent layer: size the task and decide on meta-prompting (lazy LLM)."""
        from .agents.intent import IntentAgent
        from .language import language_directive
        from .llm import wrap_structured_output
        from .state import Intent

        if self._intent_agent is None:
            models = self._ensure_role_models()
            self._intent_agent = IntentAgent(
                wrap_structured_output(models["intent"], Intent, self.settings))
        return self._intent_agent.classify(request, language_directive(request))

    def apply_budget(self, task_size: float, user_request: str = "") -> dict:
        """Scale loop/tool budgets to the task size and rebuild the graph if changed."""
        scaled = self.settings.scaled_budget(task_size)
        if task_size >= 0.5 and user_request:
            from .plan_validation import _is_architecture_task
            if _is_architecture_task(user_request):
                scaled = dict(scaled)
                scaled["max_plan_revisions"] = min(scaled["max_plan_revisions"], 1)
        if scaled == self._applied_budget:
            return scaled
        for name, value in scaled.items():
            setattr(self.settings, name, value)
        self._applied_budget = scaled
        self.log.info("budget scaled for task_size=%.2f: %s", task_size, scaled)
        # Force graph rebuild so the executor/loops pick up the new budget.
        self._graph = None
        return scaled

    def chat_reply(self, request: str) -> str:
        """Direct conversational reply for greeting-sized, non-code messages
        (skips the whole plan/execute pipeline)."""
        from .language import language_directive
        from langchain_core.messages import HumanMessage, SystemMessage

        models = self._ensure_role_models()
        system = ("You are BoBanana, a friendly terminal coding agent. Reply briefly "
                  "and naturally to this small-talk / greeting message. If the user "
                  "seems to want coding help, invite them to describe the task."
                  + language_directive(request))
        msg = models["finalize"].invoke(
            [SystemMessage(content=system), HumanMessage(content=request)])
        return msg.content if isinstance(msg.content, str) else str(msg.content)

    def triage_task(self, request: str):
        """Run the meta-prompter on a request. Returns a TaskTriage (lazy LLM)."""
        from .agents.metaprompt import MetaPrompter
        from .language import language_directive
        from .llm import wrap_structured_output
        from .state import TaskTriage

        if self._metaprompter is None:
            models = self._ensure_role_models()
            self._metaprompter = MetaPrompter(
                wrap_structured_output(models["intent"], TaskTriage, self.settings))
        return self._metaprompter.triage(request, language_directive(request))

    def run_task(self, request: str, on_event: Callable[[dict], None],
                 difficulty: float = 0.5) -> AgentState:
        graph = self._ensure_graph(on_event)
        return graph.run(request, difficulty=difficulty)

    def resume_task(self, on_event: Callable[[dict], None]) -> Optional[AgentState]:
        """Continue an interrupted task from its last checkpoint."""
        if self._graph is None:
            return None
        self._graph.on_event = on_event
        return self._graph.resume()

    def list_checkpoints(self) -> list[dict]:
        return self._graph.checkpoints() if self._graph is not None else []

    def rollback_task(self, checkpoint_id: str,
                      on_event: Callable[[dict], None]) -> Optional[AgentState]:
        if self._graph is None:
            return None
        self._graph.on_event = on_event
        return self._graph.rollback(checkpoint_id)

    def load_agent_reach(self) -> str:
        """Clone & register the Agent-Reach skill repo."""
        self.log.info("loading Agent-Reach from %s", self.settings.agent_reach_repo)
        return self.skills.clone_repo(self.settings.agent_reach_repo, name="Agent-Reach")

    def _make_toolbox(self):
        from .tools import Toolbox

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
        )

    def list_tools(self) -> list[dict]:
        """Return the executor tool catalog (registry metadata, not a filesystem scan)."""
        return self._make_toolbox().catalog()

    def reload_tools(self) -> str:
        """Hot-rescan ``.bobanana/tools/`` and invalidate the cached graph."""
        tb = self._make_toolbox()
        self._graph = None
        report = tb._plugin_loader.report if tb._plugin_loader else None
        loaded = len(report.loaded) if report else 0
        errors = len(report.errors) if report else 0
        return (f"OK: {len(tb.catalog())} tool(s) registered; "
                f"plugins loaded={loaded}, errors={errors}; "
                f"dir={tb.plugin_dir}")

    def set_workspace(self, new_workspace: Path) -> str:
        """Switch the active code workspace at runtime.

        Rebuilds the file/shell tools (via a fresh graph) and re-points the memory
        stores at the new workspace's data dir.
        """
        new_workspace = Path(new_workspace).resolve()
        if not new_workspace.is_dir():
            return f"ERROR: not a directory: {new_workspace}"

        self.log.info("switching workspace -> %s", new_workspace)
        self.settings.workspace = new_workspace
        self.settings.data_dir = resolve_data_dir(new_workspace)
        self.settings.mcp_config = new_workspace / "mcp.json"
        self.settings.skill_dirs = default_skill_dirs(new_workspace)
        self.settings.ensure_dirs()

        # Re-point memory at the new workspace's stores (close old handles first).
        self.memory.close()
        self.memory = MemoryManager(
            self.settings.data_dir, workspace=new_workspace)
        # Re-discover skills/MCP for this workspace and reset graph/toolbox.
        self.skills = SkillRegistry(self.settings.skill_dirs, self.settings.external_dir)
        self.mcp = McpManager(self.settings.mcp_config)
        self._mcp_tools = self.mcp.load()[0]
        self._graph = None
        self._applied_budget = None
        return (f"OK: workspace set to {new_workspace}\n"
                f"memory store: {self.settings.data_dir} (session working memory cleared)")

    def close(self) -> None:
        self.memory.close()

    # ----- offline self-check -----
    def selfcheck(self) -> list[tuple[str, bool, str]]:
        results: list[tuple[str, bool, str]] = []

        def check(name: str, fn):
            try:
                detail = fn()
                results.append((name, True, detail or "ok"))
            except Exception as exc:
                results.append((name, False, f"{type(exc).__name__}: {exc}"))

        check("settings", lambda: f"workspace={self.settings.workspace}, model={self.settings.model}, "
                                  f"log_level={self.settings.log_level}")

        def mem_roundtrip() -> str:
            self.memory.remember_turn("user", "selfcheck conversation about caching layers")
            recalled = self.memory.recall_conversation("caching")
            self.memory.record_fact("selfcheck", "passed", category="diagnostic")
            self.memory.record_file("selfcheck.txt", "diagnostic file", 1)
            assert self.memory.structured.get_fact("selfcheck") == "passed"
            assert "caching" in recalled  # keyword recall over working memory
            return f"recall_len={len(recalled)}, summary={self.memory.summary()}"

        check("memory (working+structured)", mem_roundtrip)

        def skills_check() -> str:
            names = [s.name for s in self.skills.list()]
            reach = "agent-reach" in [n.lower() for n in names]
            return f"discovered={len(names)} (agent-reach found={reach}): {', '.join(names[:8])}"

        check("skills", skills_check)
        check("mcp", lambda: self.mcp.status)

        def tools_roundtrip() -> str:
            from .tools import Toolbox

            tb = self._make_toolbox()
            wt = tb.get("write_file")
            rt = tb.get("read_file")
            rel = ".bobanana/selfcheck_tool.txt"
            wt.invoke({"path": rel, "content": "hello from selfcheck"})
            content = rt.invoke({"path": rel})
            cat = tb.catalog()
            sources: dict[str, int] = {}
            for entry in cat:
                sources[entry["source"]] = sources.get(entry["source"], 0) + 1
            src_str = ",".join(f"{k}={v}" for k, v in sorted(sources.items()))
            names = [e["name"] for e in cat]
            report = tb._plugin_loader.report if tb._plugin_loader else None
            plugins = len(report.loaded) if report else 0
            pdir = tb.plugin_dir
            return (f"registry={Toolbox.REGISTRY_MODULE}, count={len(cat)}, sources={{{src_str}}}, "
                    f"plugin_dir={pdir}, plugins_loaded={plugins}, "
                    f"tools={names}, read_ok={'hello' in content}")

        check("tools", tools_roundtrip)

        def graph_assembly() -> str:
            if not self.settings.has_llm:
                return "skipped (no OPENAI_API_KEY) — set it to enable live runs"
            self._ensure_graph(lambda e: None)
            return "graph compiled"

        check("graph", graph_assembly)
        return results
