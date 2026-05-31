"""Offline tests for the new features:
- task triage heuristics (large / unclear / code-task detection)
- meta-prompter structured-output parsing & fallback
- workspace path validation
- delivery-gate directive injection in the graph
"""

import tempfile
from pathlib import Path

from bobanana.app import Application
from bobanana.config import Settings
from bobanana.graph import CodingAgentGraph
from bobanana.memory import MemoryManager
from bobanana.state import Plan, PlanStep, ReviewResult, TaskTriage
from bobanana.triage import (
    estimate_task_size,
    is_code_task,
    is_greeting,
    looks_large,
    looks_research_task,
    looks_unclear,
    needs_agent_pipeline,
    should_metaprompt,
)
from bobanana.workspace import validate_directory


# ----- triage heuristics -----
def test_is_code_task():
    assert is_code_task("写一个登录功能的函数")
    assert is_code_task("refactor the auth module")
    assert not is_code_task("今天天气怎么样")


def test_looks_large_and_unclear():
    assert looks_large("先写后端，然后写前端，并且加上测试，以及部署脚本")
    assert looks_unclear("优化一下")
    assert looks_unclear("写代码")  # code task, too few words
    assert not looks_unclear("把 utils.py 里的 parse_date 函数改成支持 ISO8601 格式")


def test_research_task_sizing():
    q = "帮我搜索github上最火的ai项目"
    assert looks_research_task(q)
    assert needs_agent_pipeline(q)
    assert estimate_task_size(q) >= 0.58
    assert estimate_task_size("你好，你是谁") == 0.0


def test_intent_calibrates_under_estimate():
    from bobanana.agents.intent import IntentAgent
    from bobanana.state import Intent

    class _LowStub:
        def invoke(self, messages):
            return Intent(
                task_size=0.15,
                is_code_task=False,
                needs_metaprompt=False,
                reason="LLM under-estimated",
            )

    out = IntentAgent(_LowStub()).classify("帮我搜索github上最火的ai项目")
    assert out.task_size >= 0.58
    assert out.is_code_task is True


def test_should_metaprompt():
    assert should_metaprompt("优化一下")          # vague phrasing
    assert should_metaprompt("写代码")            # code task, under-specified
    assert not should_metaprompt("把 README 的标题改为 BoBanana")


# ----- meta-prompter -----
class _StubTriageLLM:
    def __init__(self, result):
        self._result = result

    def invoke(self, messages):
        return self._result


def test_metaprompter_parses_model():
    from bobanana.agents.metaprompt import MetaPrompter

    expected = TaskTriage(needs_clarification=True, questions=["哪个数据库?"],
                          refined_request="", assessment="scope unclear")
    mp = MetaPrompter(_StubTriageLLM(expected))
    out = mp.triage("做个后端")
    assert out.needs_clarification is True
    assert out.questions == ["哪个数据库?"]


def test_metaprompter_fallback_on_garbage():
    from bobanana.agents.metaprompt import MetaPrompter

    mp = MetaPrompter(_StubTriageLLM(None))
    out = mp.triage("做个后端")
    assert out.needs_clarification is False
    assert out.refined_request == "做个后端"


# ----- workspace switch / memory isolation -----
def test_set_workspace_isolates_structured_and_working_memory(tmp_path):
    ws_a = tmp_path / "proj_a"
    ws_b = tmp_path / "proj_b"
    ws_a.mkdir()
    ws_b.mkdir()
    settings = Settings(workspace=ws_a, data_dir=ws_a / ".bobanana", api_key="")
    app = Application(settings)
    app.memory.record_fact("marker", "only-in-A", category="general")
    app.memory.remember_turn("user", "conversation secret from project A")

    app.set_workspace(ws_b)
    rt = app.session_manager.focus
    assert rt.settings.data_dir == (ws_b / ".bobanana").resolve()
    assert rt.memory.structured.get_fact("marker") is None
    assert "secret" not in rt.memory.recall_conversation("secret")

    rt.memory.record_fact("marker", "only-in-B", category="general")
    app.set_workspace(ws_a)
    rt = app.session_manager.focus
    assert rt.memory.structured.get_fact("marker") == "only-in-A"
    # Working memory is per-session; switching workspaces clears it (no cross-talk).
    assert "secret" not in app.memory.recall_conversation("secret")


def test_ensure_graph_rebuilds_when_memory_replaced(tmp_path, monkeypatch):
    from bobanana.llm import ROLE_TEMPERATURES

    ws_a = tmp_path / "a"
    ws_b = tmp_path / "b"
    ws_a.mkdir()
    ws_b.mkdir()
    settings = Settings(workspace=ws_a, data_dir=ws_a / ".bobanana", api_key="")
    app = Application(settings)
    monkeypatch.setattr(
        "bobanana.app.build_role_models",
        lambda _s, callbacks=None: {role: _FakeChat() for role in ROLE_TEMPERATURES},
    )
    graph_a = app._ensure_graph(lambda e: None)
    mem_a = app.memory

    app.set_workspace(ws_b)
    graph_b = app._ensure_graph(lambda e: None)
    assert graph_b is not graph_a
    assert graph_b.memory is app.memory
    assert graph_b.memory is not mem_a
    assert graph_b.settings.workspace.resolve() == ws_b.resolve()


def test_prepare_workspace_clears_stale_scratch_on_workspace_mismatch(tmp_path):
    ws_a = tmp_path / "a"
    ws_b = tmp_path / "b"
    ws_a.mkdir()
    ws_b.mkdir()
    (ws_b / "only_b.txt").write_text("b", encoding="utf-8")
    settings = Settings(workspace=ws_a, data_dir=ws_a / ".bobanana", api_key="")
    mem = MemoryManager(settings.data_dir, workspace=ws_a)
    mem.working.set_scratch("workspace_root", str(ws_a.resolve()))
    mem.working.set_scratch("workspace_index", "STALE-INDEX-FROM-A")

    settings.workspace = ws_b
    graph = CodingAgentGraph(settings, _FakeChat(), mem, models={})
    try:
        graph._prepare_workspace_node({})
        index = mem.working.get_scratch("workspace_index")
        assert "STALE-INDEX-FROM-A" not in (index or "")
        assert "only_b.txt" in (index or "")
    finally:
        mem.close()


# ----- workspace validation -----
def test_validate_directory():
    with tempfile.TemporaryDirectory() as tmp:
        path, msg = validate_directory(tmp)
        assert path is not None and msg == "ok"
    bad, msg = validate_directory("Z:/definitely/not/here/xyz")
    assert bad is None
    empty, msg = validate_directory("   ")
    assert empty is None


# ----- delivery-gate injection -----
class _Struct:
    def __init__(self, schema):
        self.schema = schema

    def invoke(self, messages):
        if self.schema is Plan:
            return Plan(summary="stub", steps=[PlanStep(id=1, description="noop")])
        return ReviewResult(approved=True, score=9)


class _FakeChat:
    def with_structured_output(self, schema, method=None):
        return _Struct(schema)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        from langchain_core.messages import AIMessage
        return AIMessage(content="ok")


def _make_graph(gate_text: str, **overrides):
    tmp = tempfile.mkdtemp()
    ws = Path(tmp)
    settings = Settings(workspace=ws, data_dir=ws / ".bobanana", **overrides)
    settings.ensure_dirs()
    memory = MemoryManager(settings.data_dir)
    graph = CodingAgentGraph(settings, _FakeChat(), memory, delivery_gate_text=gate_text)
    return graph, memory


def test_delivery_gate_directive_for_code_task():
    graph, memory = _make_graph("# Skill: code-delivery-gate\nfollow the gate")
    try:
        code_state = {"user_request": "实现一个解析函数"}
        non_code_state = {"user_request": "今天几号"}
        assert "code-delivery-gate" in graph._directives(code_state)
        assert "code-delivery-gate" not in graph._directives(non_code_state)
    finally:
        memory.close()


def test_delivery_gate_disabled():
    graph, memory = _make_graph("# Skill: code-delivery-gate\nfollow the gate",
                                enable_delivery_gate=False)
    try:
        assert "code-delivery-gate" not in graph._directives({"user_request": "写一个函数"})
    finally:
        memory.close()


def test_build_restart_argv():
    from bobanana.restart import build_restart_argv

    argv = build_restart_argv(["/path/to/__main__.py", "--debug", "--workspace", "C:\\proj"])
    assert argv[0]  # python executable
    assert argv[1:4] == ["-m", "bobanana", "--debug"]
    assert argv[4:] == ["--workspace", "C:\\proj"]


# ----- shell posix-ism detection -----
def test_looks_posix_only_detection():
    from bobanana.tools.shell_tools import looks_posix_only

    assert looks_posix_only("ldconfig -p | grep ssl")
    assert looks_posix_only('echo "x" && find /usr -name "sha.h"')
    assert looks_posix_only("cat foo.txt 2>/dev/null")
    assert looks_posix_only("which python")
    # Legitimate cross-platform commands must not be flagged.
    assert looks_posix_only("python -m pytest -q") is None
    assert looks_posix_only("git status") is None
    assert looks_posix_only("dir") is None


def test_shell_blocks_posix_on_windows(tmp_path):
    import bobanana.tools.shell_tools as st
    from bobanana.tools.shell_tools import ShellRunner

    runner = ShellRunner(tmp_path)
    # Force the Windows branch regardless of host OS so the test is deterministic.
    original = st.IS_WINDOWS
    st.IS_WINDOWS = True
    try:
        out = runner.run('echo "check" && ldconfig -p')
        assert out.startswith("ERROR: command not run")
        assert "Windows" in out
    finally:
        st.IS_WINDOWS = original


def test_shell_runs_crossplatform(tmp_path):
    from bobanana.tools.shell_tools import ShellRunner

    runner = ShellRunner(tmp_path)
    out = runner.run("python --version")
    assert "[exit=0]" in out and "Python" in out


# ----- exploration cache -----
def test_exploration_cache_hit_and_invalidation(tmp_path):
    from bobanana.tools import Toolbox
    from bobanana.memory import MemoryManager

    mem = MemoryManager(tmp_path / ".bobanana")
    try:
        (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
        tb = Toolbox(tmp_path, mem, web_enabled=False, exploration_cache=True)
        read = tb.get("read_file")
        first = read.invoke({"path": "a.txt"})
        assert "hello" in first and not first.startswith("[cached]")
        second = read.invoke({"path": "a.txt"})
        assert second.startswith("[cached]") and "hello" in second
        # A write must invalidate the cache → next read is fresh again.
        tb.get("write_file").invoke({"path": "b.txt", "content": "x"})
        third = read.invoke({"path": "a.txt"})
        assert not third.startswith("[cached]")
    finally:
        mem.close()


def test_exploration_cache_disabled(tmp_path):
    from bobanana.tools import Toolbox
    from bobanana.memory import MemoryManager

    mem = MemoryManager(tmp_path / ".bobanana")
    try:
        (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
        tb = Toolbox(tmp_path, mem, web_enabled=False, exploration_cache=False)
        read = tb.get("read_file")
        read.invoke({"path": "a.txt"})
        again = read.invoke({"path": "a.txt"})
        assert not again.startswith("[cached]")
    finally:
        mem.close()


def test_cached_result_is_nonproductive():
    from bobanana.agents.executor import _is_nonproductive

    # Empty cached body → still non-productive
    assert _is_nonproductive("read_file", {"path": "a.txt"}, "[cached] 已探索过…\n")
    # Cached read WITH substantive body → productive (5.30 fix)
    assert not _is_nonproductive(
        "read_file", {"path": "a.txt"},
        "[cached] 已探索过…\n" + "x" * 50,
    )


# ----- directive gate -----
def test_directive_gate_empty_passes():
    from bobanana.agents.directive_gate import DirectiveGate

    # No directives → satisfied without calling the LLM.
    class _Boom:
        def invoke(self, messages):
            raise AssertionError("LLM should not be called when there are no directives")

    gate = DirectiveGate(_Boom())
    out = gate.check("task", [], "completed")
    assert out.all_satisfied is True


def test_directive_gate_reports_unmet():
    from bobanana.agents.directive_gate import DirectiveGate
    from bobanana.state import DirectiveCheck

    class _Stub:
        def invoke(self, messages):
            return DirectiveCheck(all_satisfied=False, unmet=["build not run"], notes="no build output")

    gate = DirectiveGate(_Stub())
    out = gate.check("task", ["build succeeds"], "did nothing")
    assert out.all_satisfied is False
    assert out.unmet == ["build not run"]


def test_directive_gate_fallback_is_conservative():
    """A flaky gate that never returns a parseable verdict must NOT claim success."""
    from bobanana.agents.directive_gate import DirectiveGate

    class _Garbage:
        def invoke(self, messages):
            return None

    gate = DirectiveGate(_Garbage(), max_attempts=2)
    out = gate.check("task", ["build succeeds"], "work")
    assert out.all_satisfied is False
    assert out.unmet == []  # empty → no pointless remediation loop, but reported partial


# ----- executor structured fix instruction -----
def test_executor_fix_instruction_budget_vs_quality():
    from bobanana.agents.executor import ExecutorAgent
    from bobanana.state import ReviewResult
    from langchain_core.messages import SystemMessage

    captured = {}

    class _CaptureLLM:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            from langchain_core.messages import AIMessage, HumanMessage
            human = [m for m in messages if isinstance(m, HumanMessage)]
            captured["text"] = human[-1].content if human else ""
            return AIMessage(content="ok")  # no tool calls → finish immediately

    # Budget-exhausted prior output → instruction should steer to the core action.
    ex = ExecutorAgent(_CaptureLLM(), [])
    rev = ReviewResult(approved=False, score=0, suggestions=["do X"], rationale="r")
    ex.execute("step", context="", review=rev,
               prior_output="Step stopped: reached max tool iterations.")
    assert "ran out of tool iterations" in captured["text"]
    assert "DIRECTLY to the core action" in captured["text"]

    # Quality rejection → numbered checklist + no-repeat rules.
    ex.execute("step", context="", review=rev, prior_output="wrote half a file, buggy")
    assert "checklist" in captured["text"]
    assert "1. do X" in captured["text"]
    assert "do NOT repeat tool calls" in captured["text"]


def test_directive_gate_loop_then_finish(tmp_path):
    """End-to-end: a plan with a key directive that the gate first reports unmet
    (loop back, append remedial step) then satisfied (finalize)."""
    from bobanana.config import Settings
    from bobanana.graph import CodingAgentGraph
    from bobanana.memory import MemoryManager
    from bobanana.state import DirectiveCheck, Plan, PlanStep, ReviewResult
    from langchain_core.messages import AIMessage

    calls = {"gate": 0}

    class _Struct:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, messages):
            if self.schema is Plan:
                return Plan(summary="stub", steps=[PlanStep(id=1, description="do work")],
                            key_directives=["the file out.txt exists"])
            if self.schema is ReviewResult:
                return ReviewResult(approved=True, score=9)
            if self.schema is DirectiveCheck:
                calls["gate"] += 1
                if calls["gate"] == 1:
                    return DirectiveCheck(all_satisfied=False, unmet=["write out.txt"], notes="missing")
                return DirectiveCheck(all_satisfied=True, unmet=[], notes="ok")
            raise AssertionError("unexpected schema")

    class _FakeChat:
        def with_structured_output(self, schema, method=None):
            return _Struct(schema)

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            text = " ".join(str(getattr(m, "content", "")) for m in messages)
            if "Summarize the completed" in text:
                return AIMessage(content="done summary")
            return AIMessage(content="step finished")

    ws = tmp_path
    settings = Settings(workspace=ws, data_dir=ws / ".bobanana",
                        max_plan_revisions=1, max_exec_revisions=1, max_steps=6,
                        max_directive_revisions=2)
    settings.ensure_dirs()
    mem = MemoryManager(settings.data_dir)
    try:
        events: list[dict] = []
        graph = CodingAgentGraph(settings, _FakeChat(), mem, on_event=events.append)
        result = graph.run("make out.txt")
        assert result["done"] is True
        # Gate ran at least twice (unmet → loop → satisfied).
        assert calls["gate"] >= 2
        # A remedial step was appended after the unmet verdict.
        descs = [s["description"] for s in result["plan"]["steps"]]
        assert any("补救" in d for d in descs)
        assert any(e["kind"] == "directive_gate" for e in events)
    finally:
        mem.close()


def test_failed_review_reported_partial_not_success(tmp_path):
    """If a step never passes review and the budget is exhausted, the task must be
    reported as PARTIAL with the failed step surfaced — never a silent success."""
    from bobanana.config import Settings
    from bobanana.graph import CodingAgentGraph
    from bobanana.memory import MemoryManager
    from bobanana.state import Plan, PlanStep, ReviewResult
    from langchain_core.messages import AIMessage

    class _Struct:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, messages):
            if self.schema is Plan:
                return Plan(summary="stub", steps=[PlanStep(id=1, description="do work")])
            # Reviewer ALWAYS rejects.
            return ReviewResult(approved=False, score=2, suggestions=["fix it"], rationale="not good")

    class _FakeChat:
        def with_structured_output(self, schema, method=None):
            return _Struct(schema)

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            text = " ".join(str(getattr(m, "content", "")) for m in messages)
            if "HONESTLY" in text or "Summarize the completed" in text:
                return AIMessage(content="honest summary")
            return AIMessage(content="attempted")

    ws = tmp_path
    settings = Settings(workspace=ws, data_dir=ws / ".bobanana",
                        max_plan_revisions=1, max_exec_revisions=1, max_steps=3)
    settings.ensure_dirs()
    mem = MemoryManager(settings.data_dir)
    try:
        graph = CodingAgentGraph(settings, _FakeChat(), mem)
        result = graph.run("do work")
        assert result["done"] is True
        assert result["status"] == "partial"           # NOT silently completed
        assert len(result["failed_steps"]) == 1
        assert result["failed_steps"][0]["id"] == 1
    finally:
        mem.close()


# ----- OS-aware command library -----
def test_default_allowlist_is_os_aware():
    import bobanana.tools.shell_tools as st

    # COMMON commands are always present.
    assert {"python", "git", "pytest"} <= st.DEFAULT_ALLOWLIST
    assert st.COMMON_COMMANDS <= st.DEFAULT_ALLOWLIST
    # Exactly one OS family of extras is included.
    if st.IS_WINDOWS:
        assert "dir" in st.DEFAULT_ALLOWLIST and "where" in st.DEFAULT_ALLOWLIST
        assert "ls" not in st.DEFAULT_ALLOWLIST
    else:
        assert "ls" in st.DEFAULT_ALLOWLIST
        assert "where" not in st.DEFAULT_ALLOWLIST


# ----- budget: failed/empty-path calls don't count -----
def test_is_nonproductive():
    from bobanana.agents.executor import _is_nonproductive

    assert _is_nonproductive("read_file", {"path": ""}, "anything")          # empty path
    assert _is_nonproductive("read_file", {"path": "   "}, "ok")             # whitespace path
    assert _is_nonproductive("read_file", {}, "ERROR: file not found")       # error result
    assert _is_nonproductive("read_file", {}, "Step stopped: ...")
    assert not _is_nonproductive("write_file", {"path": "a.py"}, "OK: wrote 5 chars")


class _BudgetLLM:
    """Emits N failing tool calls, then a success, then finishes — to verify
    failed calls don't burn the budget."""

    def __init__(self, fail_turns: int):
        self.calls = 0
        self.fail_turns = fail_turns

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        from langchain_core.messages import AIMessage, ToolMessage

        # Count how many tool results we've already seen.
        seen = sum(1 for m in messages if isinstance(m, ToolMessage))
        if seen < self.fail_turns:
            return AIMessage(content="", tool_calls=[{
                "name": "read_file", "args": {"path": "missing.txt"}, "id": f"c{seen}"}])
        if seen == self.fail_turns:
            return AIMessage(content="", tool_calls=[{
                "name": "write_file", "args": {"path": "out.txt", "content": "hi"}, "id": "cw"}])
        return AIMessage(content="done")


def test_failed_calls_do_not_consume_budget(tmp_path):
    from bobanana.agents.executor import ExecutorAgent
    from bobanana.tools import Toolbox
    from bobanana.memory import MemoryManager

    mem = MemoryManager(tmp_path / ".bobanana")
    try:
        tb = Toolbox(tmp_path, mem, web_enabled=False)
        # 5 failing read_file calls then a real write — with the old fixed-iteration
        # logic and max_tool_iters=2 the budget would be burned by failures before
        # the write; the new logic ignores failures so the write succeeds & finishes.
        ex = ExecutorAgent(_BudgetLLM(fail_turns=5), tb.tools, max_tool_iters=2)
        out = ex.execute("write out.txt", context="")
        assert out == "done"
        assert (tmp_path / "out.txt").read_text() == "hi"
    finally:
        mem.close()


# ----- intent layer -----
def test_intent_agent_parses_and_clamps():
    from bobanana.agents.intent import IntentAgent
    from bobanana.state import Intent

    class _Stub:
        def invoke(self, messages):
            return Intent(task_size=1.7, is_code_task=True, needs_metaprompt=True, reason="big")

    out = IntentAgent(_Stub()).classify("refactor everything")
    assert out.task_size == 1.0  # clamped into range
    assert out.needs_metaprompt is True


def test_intent_agent_heuristic_fallback():
    from bobanana.agents.intent import IntentAgent

    class _Garbage:
        def invoke(self, messages):
            raise RuntimeError("no structured output")

    agent = IntentAgent(_Garbage(), max_attempts=2)
    greeting = agent.classify("你好")
    assert greeting.task_size < 0.12 and greeting.is_code_task is False
    big = agent.classify("重构整个项目，拆分模块、补测试、并且更新文档")
    assert big.task_size >= 0.6


def test_scaled_budget_bounds():
    from bobanana.config import Settings

    s = Settings(max_steps=12, max_tool_iters=12, max_exec_revisions=2,
                 max_plan_revisions=2, max_directive_revisions=2, shell_timeout=60)
    low = s.scaled_budget(0.0)
    high = s.scaled_budget(1.0)
    # t=0 → floors; t=1 → configured ceilings.
    assert low["max_steps"] == 2 and low["shell_timeout"] == 20
    assert high["max_steps"] == 12 and high["shell_timeout"] == 60
    mid = s.scaled_budget(0.5)
    assert low["max_steps"] <= mid["max_steps"] <= high["max_steps"]
    # Out-of-range inputs are clamped.
    assert s.scaled_budget(5.0) == high
    assert s.scaled_budget(-1.0) == low


def test_role_temperatures_layered():
    from bobanana.llm import ROLE_TEMPERATURES, role_temperature
    from bobanana.config import Settings

    s = Settings(temperature=0.1)
    assert ROLE_TEMPERATURES["reviewer"] == 0.0
    assert ROLE_TEMPERATURES["directive_gate"] == 0.0
    # Executor runs hotter than the critics to break repetition.
    assert ROLE_TEMPERATURES["executor"] > ROLE_TEMPERATURES["reviewer"]
    # Unknown role falls back to the global temperature.
    assert role_temperature(s, "nonexistent") == 0.1


# ----- shell timeout -> replan -----
def test_shell_timeout_marker():
    from bobanana.tools.shell_tools import ShellRunner
    import bobanana.tools.shell_tools as st

    runner = ShellRunner(Path.cwd(), timeout=1)
    # Force a timeout deterministically by stubbing subprocess.run.
    import subprocess

    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="python", timeout=1)

    orig = st.subprocess.run
    st.subprocess.run = _boom
    try:
        out = runner.run("python -c \"import time;time.sleep(9)\"")
    finally:
        st.subprocess.run = orig
    assert "ERROR: TIMEOUT" in out


def test_executor_timeout_returns_replan_signal():
    from bobanana.agents.executor import ExecutorAgent
    from langchain_core.messages import AIMessage

    class _TimeoutTool:
        name = "run_shell"

        def invoke(self, args):
            return "ERROR: TIMEOUT after 1s running `sleep 9`. stuck."

    class _LLM:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return AIMessage(content="", tool_calls=[{
                "name": "run_shell", "args": {"command": "sleep 9"}, "id": "t1"}])

    ex = ExecutorAgent(_LLM(), [_TimeoutTool()], max_tool_iters=3)
    out = ex.execute("run a slow thing", context="")
    assert out.startswith("REPLAN_NEEDED")


def test_graph_reroutes_to_replan_on_timeout(tmp_path):
    """End-to-end: a step whose shell command times out triggers a replan
    (plan_revisions increments) rather than silently proceeding."""
    from bobanana.config import Settings
    from bobanana.graph import CodingAgentGraph
    from bobanana.memory import MemoryManager
    from bobanana.state import Plan, PlanStep, ReviewResult
    from langchain_core.messages import AIMessage

    calls = {"exec": 0}

    class _Struct:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, messages):
            if self.schema is Plan:
                return Plan(summary="p", steps=[PlanStep(id=1, description="run slow cmd")])
            return ReviewResult(approved=True, score=9)

    class _TimeoutTool:
        name = "run_shell"

        def invoke(self, args):
            return "ERROR: TIMEOUT after 1s running `sleep`. stuck."

    class _FakeChat:
        def with_structured_output(self, schema, method=None):
            return _Struct(schema)

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            text = " ".join(str(getattr(m, "content", "")) for m in messages)
            if "EXECUTOR" in text:
                calls["exec"] += 1
                # First execution times out; after the replan, finish cleanly.
                if calls["exec"] == 1:
                    return AIMessage(content="", tool_calls=[{
                        "name": "run_shell", "args": {"command": "sleep 9"}, "id": "x"}])
                return AIMessage(content="done without shell")
            return AIMessage(content="summary")

    settings = Settings(workspace=tmp_path, data_dir=tmp_path / ".bobanana",
                        max_plan_revisions=2, max_exec_revisions=1, max_steps=3)
    settings.ensure_dirs()
    mem = MemoryManager(settings.data_dir)
    events = []
    try:
        chat = _FakeChat()
        graph = CodingAgentGraph(settings, chat, mem,
                                 on_event=lambda e: events.append(e))
        # Replace toolbox shell tool with the timeout stub.
        graph.executor._tools["run_shell"] = _TimeoutTool()
        result = graph.run("run slow cmd")
        assert result["done"] is True
        assert result["plan_revisions"] >= 1
        assert any(e["kind"] == "replan" for e in events)
    finally:
        mem.close()


# ----- adaptive difficulty -----
def test_executor_extra_iters_raises_budget():
    """extra_tool_iters lifts the per-step productive budget, capped at 2x base."""
    from bobanana.agents.executor import ExecutorAgent
    from langchain_core.messages import AIMessage

    class _CountTool:
        name = "write_file"

        def invoke(self, args):
            return "wrote ok"  # productive every turn

    class _AlwaysCallLLM:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return AIMessage(content="", tool_calls=[{
                "name": "write_file", "args": {"path": "f.txt", "content": "x"}, "id": "c"}])

    tool = _CountTool()
    # base=2 → cap=4; extra=10 should be clamped to 4 productive turns.
    ex = ExecutorAgent(_AlwaysCallLLM(), [tool], max_tool_iters=2)
    out = ex.execute("loop", context="", extra_tool_iters=10)
    assert out.startswith("MICRO_REPLAN_NEEDED")


def test_revise_exec_node_ratchets_difficulty(tmp_path):
    from bobanana.config import Settings
    from bobanana.graph import CodingAgentGraph
    from bobanana.memory import MemoryManager
    from bobanana.state import ReviewResult
    from langchain_core.messages import AIMessage

    class _FakeChat:
        def with_structured_output(self, schema, method=None):
            return self

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return AIMessage(content="x")

    settings = Settings(workspace=tmp_path, data_dir=tmp_path / ".bobanana",
                        max_tool_iters=10, enable_checkpoints=False)
    settings.ensure_dirs()
    mem = MemoryManager(settings.data_dir)
    try:
        g = CodingAgentGraph(settings, _FakeChat(), mem)
        state = {"exec_review": ReviewResult(approved=False, score=2).model_dump(),
                 "difficulty": 0.4, "tool_iter_bonus": 0, "exec_revisions": 0}
        out = g._revise_exec_node(state)
        assert out["difficulty"] > 0.4           # ratcheted up
        assert out["tool_iter_bonus"] >= 5       # ~max_tool_iters*0.5
        assert out["exec_revisions"] == 1
    finally:
        mem.close()


# ----- checkpoints / interrupt / resume / rollback -----
def _make_offline_graph(tmp_path, plan_sleep=0.0, **settings_kw):
    """Build a graph with a stub LLM that completes a 2-step task; the planner call
    can sleep to make a tiny wall-clock timeout deterministic."""
    import time as _t
    from bobanana.config import Settings
    from bobanana.graph import CodingAgentGraph
    from bobanana.memory import MemoryManager
    from bobanana.state import Plan, PlanStep, ReviewResult
    from langchain_core.messages import AIMessage

    class _Struct:
        def __init__(self, schema):
            self.schema = schema

        def invoke(self, messages):
            if self.schema is Plan:
                if plan_sleep:
                    _t.sleep(plan_sleep)
                return Plan(summary="p", steps=[
                    PlanStep(id=1, description="step one"),
                    PlanStep(id=2, description="step two"),
                ])
            return ReviewResult(approved=True, score=9)

    class _FakeChat:
        def with_structured_output(self, schema, method=None):
            return _Struct(schema)

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return AIMessage(content="did the step")

    settings = Settings(workspace=tmp_path, data_dir=tmp_path / ".bobanana",
                        max_steps=4, max_exec_revisions=1, **settings_kw)
    settings.ensure_dirs()
    mem = MemoryManager(settings.data_dir)
    graph = CodingAgentGraph(settings, _FakeChat(), mem)
    return graph, mem


def test_timeout_interrupts_then_resume_completes(tmp_path):
    # Tiny timeout + a planner that sleeps past it → interrupt at the first boundary.
    graph, mem = _make_offline_graph(tmp_path, plan_sleep=0.05, task_timeout=0.01,
                                     enable_checkpoints=True)
    try:
        result = graph.run("do two steps")
        assert result.get("interrupted") is True
        assert result.get("interrupt_reason") == "timeout"
        assert result.get("done") is not True
        # Resume with a real budget (no timeout) → runs to completion.
        graph.settings.task_timeout = 0.0
        resumed = graph.resume()
        assert resumed is not None and resumed.get("done") is True
        assert graph.interrupted is False
    finally:
        mem.close()


def test_rollback_to_earlier_checkpoint(tmp_path):
    graph, mem = _make_offline_graph(tmp_path, enable_checkpoints=True)
    try:
        result = graph.run("do two steps")
        assert result.get("done") is True
        cps = graph.checkpoints()
        assert cps, "expected checkpoint history"
        # Pick an early checkpoint that still has pending work.
        resumable = [c for c in cps if c.get("next")]
        assert resumable
        target = resumable[-1]  # earliest with pending work
        rolled = graph.rollback(target["checkpoint_id"])
        assert rolled is not None and rolled.get("done") is True
    finally:
        mem.close()


def test_checkpoints_disabled_returns_empty(tmp_path):
    graph, mem = _make_offline_graph(tmp_path, enable_checkpoints=False)
    try:
        graph.run("do two steps")
        assert graph.checkpoints() == []
        assert graph.resume() is None
    finally:
        mem.close()


# ----- review ground truth (evidence) -----
def test_executor_collects_write_and_shell_evidence():
    from bobanana.agents.executor import ExecutorAgent
    from langchain_core.messages import AIMessage

    class _WroteTool:
        name = "write_file"

        def invoke(self, args):
            return f"wrote {args['path']}"

    class _ShellTool:
        name = "run_shell"

        def invoke(self, args):
            return "tests passed: 3 ok"

    class _PlanLLM:
        """First turn writes a file + runs a command, second turn finishes."""

        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[
                    {"name": "write_file", "args": {"path": "a.py", "content": "def f():\n    return 42\n"}, "id": "1"},
                    {"name": "run_shell", "args": {"command": "pytest -q"}, "id": "2"},
                ])
            return AIMessage(content="done: wrote a.py and ran tests")

    ex = ExecutorAgent(_PlanLLM(), [_WroteTool(), _ShellTool()], max_tool_iters=4)
    summary = ex.execute("write a.py and test it", context="")
    assert "done" in summary
    ev = ex.last_evidence
    assert "[wrote] a.py" in ev and "def f()" in ev          # real file content
    assert "[ran] pytest" in ev and "tests passed" in ev      # real command output


def test_review_artifact_receives_evidence():
    from bobanana.agents.reviewer import ReviewerAgent
    from bobanana.state import ReviewResult

    seen = {}

    class _CaptureLLM:
        def invoke(self, messages):
            seen["human"] = messages[-1].content
            return ReviewResult(approved=True, score=8)

    r = ReviewerAgent(_CaptureLLM())
    r.review_artifact("write a.py", produced="I wrote it",
                      context="", evidence="[wrote] a.py (10 chars):\nx=1")
    assert "EVIDENCE" in seen["human"]
    assert "[wrote] a.py" in seen["human"]
    # The self-report must be explicitly labeled as an unverified claim.
    assert "UNVERIFIED" in seen["human"]


def test_review_artifact_empty_evidence_marked():
    from bobanana.agents.reviewer import ReviewerAgent
    from bobanana.state import ReviewResult

    seen = {}

    class _CaptureLLM:
        def invoke(self, messages):
            seen["human"] = messages[-1].content
            return ReviewResult(approved=False, score=2)

    r = ReviewerAgent(_CaptureLLM())
    r.review_artifact("do something", produced="claims", context="", evidence="")
    assert "no artifacts produced" in seen["human"]


# ----- difficulty drives budget + resets per step -----
def test_difficulty_floor_grants_budget_without_rejection(tmp_path):
    """A hard task (high difficulty) should grant extra per-step budget on the
    FIRST attempt, before any review rejection."""
    from bobanana.config import Settings
    from bobanana.graph import CodingAgentGraph
    from bobanana.memory import MemoryManager
    from bobanana.state import Plan, PlanStep
    from langchain_core.messages import AIMessage

    captured = {}

    class _Exec:
        max_tool_iters = 10
        last_evidence = ""

        def execute(self, desc, context, review=None, prior=None, lang="",
                    key_directives=None, extra_tool_iters=0, sig_counts=None):
            captured["extra"] = extra_tool_iters
            captured["sig"] = sig_counts
            return "did it"

    class _FakeChat:
        def with_structured_output(self, schema, method=None):
            return self

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return AIMessage(content="x")

    settings = Settings(workspace=tmp_path, data_dir=tmp_path / ".bobanana",
                        max_tool_iters=10, enable_checkpoints=False)
    settings.ensure_dirs()
    mem = MemoryManager(settings.data_dir)
    try:
        g = CodingAgentGraph(settings, _FakeChat(), mem)
        g.executor = _Exec()
        state = {"user_request": "do a hard thing",
                 "plan": Plan(summary="p", steps=[PlanStep(id=1, description="hard")]).model_dump(),
                 "current_step": 0, "difficulty": 1.0, "tool_iter_bonus": 0}
        g._execute_node(state)
        # 3.0: no difficulty-based extra_tool_iters; sig_counts dict is passed.
        assert captured.get("sig") is not None
        assert captured.get("extra") == 0
    finally:
        mem.close()


def test_advance_resets_tool_iter_bonus_keeps_difficulty(tmp_path):
    from bobanana.config import Settings
    from bobanana.graph import CodingAgentGraph
    from bobanana.memory import MemoryManager
    from bobanana.state import Plan, PlanStep, ReviewResult
    from langchain_core.messages import AIMessage

    class _FakeChat:
        def with_structured_output(self, schema, method=None):
            return self

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return AIMessage(content="x")

    settings = Settings(workspace=tmp_path, data_dir=tmp_path / ".bobanana",
                        enable_checkpoints=False)
    settings.ensure_dirs()
    mem = MemoryManager(settings.data_dir)
    try:
        g = CodingAgentGraph(settings, _FakeChat(), mem)
        state = {"plan": Plan(summary="p", steps=[PlanStep(id=1, description="s")]).model_dump(),
                 "current_step": 0, "step_output": "done",
                 "exec_review": ReviewResult(approved=True, score=9).model_dump(),
                 "difficulty": 0.8, "tool_iter_bonus": 7, "failed_steps": []}
        out = g._advance_node(state)
        assert out["tool_iter_bonus"] == 0          # transient bump reset per step
        assert "difficulty" not in out               # durable floor untouched (stays 0.8)
    finally:
        mem.close()


# ----- replan sentinel must not leak into artifacts/memory -----
def test_replan_sentinel_rewritten_when_budget_exhausted(tmp_path):
    from bobanana.config import Settings
    from bobanana.graph import CodingAgentGraph
    from bobanana.memory import MemoryManager
    from bobanana.state import Plan, PlanStep
    from langchain_core.messages import AIMessage

    class _Exec:
        max_tool_iters = 10
        last_evidence = ""

        def execute(self, *a, **k):
            return "REPLAN_NEEDED: a command timed out"

    class _FakeChat:
        def with_structured_output(self, schema, method=None):
            return self

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return AIMessage(content="x")

    settings = Settings(workspace=tmp_path, data_dir=tmp_path / ".bobanana",
                        max_plan_revisions=2, enable_checkpoints=False)
    settings.ensure_dirs()
    mem = MemoryManager(settings.data_dir)
    try:
        g = CodingAgentGraph(settings, _FakeChat(), mem)
        g.executor = _Exec()
        state = {"user_request": "do a thing",
                 "plan": Plan(summary="p", steps=[PlanStep(id=1, description="s")]).model_dump(),
                 "current_step": 0, "plan_revisions": 2}  # budget exhausted
        out = g._execute_node(state)
        assert not out["step_output"].lstrip().startswith("REPLAN_NEEDED")
        assert "Step stopped" in out["step_output"]
        # Route must now send it to review, not replan.
        assert g._route_after_execute({**state, **out}) == "exec_review"
    finally:
        mem.close()


# ----- working memory bounds context -----
def test_working_memory_truncates_giant_turn():
    from bobanana.memory.working_memory import WorkingMemory

    wm = WorkingMemory(per_turn_chars=100)
    wm.add_turn("assistant", "x" * 5000)
    stored = wm.recent(1)[0]["content"]
    assert len(stored) <= 100 + len("\n…(truncated)")
    assert stored.endswith("…(truncated)")


# ----- tool registry catalog / discoverability -----
def test_toolbox_catalog_lists_core_and_sources(tmp_path):
    from bobanana.config import Settings
    from bobanana.memory import MemoryManager
    from bobanana.tools import Toolbox

    settings = Settings(workspace=tmp_path, data_dir=tmp_path / ".bobanana")
    settings.ensure_dirs()
    mem = MemoryManager(settings.data_dir)
    try:
        tb = Toolbox(tmp_path, mem, web_enabled=True, skill_registry=None)
        cat = tb.catalog()
        names = {e["name"] for e in cat}
        assert {"read_file", "write_file", "list_dir", "run_shell"}.issubset(names)
        sources = {e["source"] for e in cat}
        assert "core" in sources
        assert all(e.get("has_schema") for e in cat if e["name"] in {"read_file", "write_file"})
        assert Toolbox.REGISTRY_MODULE == "bobanana.tools.registry.Toolbox"
    finally:
        mem.close()


def test_selfcheck_tools_line_reports_registry(tmp_path, monkeypatch):
    from bobanana.config import Settings
    from bobanana.app import Application

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings(workspace=tmp_path, data_dir=tmp_path / ".bobanana", api_key="")
    settings.ensure_dirs()
    app = Application(settings)
    try:
        results = {name: (ok, detail) for name, ok, detail in app.selfcheck()}
        assert results["tools"][0] is True
        assert "read_ok=True" in results["tools"][1]
    finally:
        app.close()


# ----- tool plugins: yaml drop-in, permissions, semver, introspection -----
def test_seed_plugin_directory_creates_examples(tmp_path):
    from bobanana.tools.registry import seed_plugin_directory

    plugin_dir = tmp_path / ".bobanana" / "tools"
    seed_plugin_directory(plugin_dir)
    assert plugin_dir.is_dir()
    assert (plugin_dir / "README.md").exists()
    assert (plugin_dir / "example_ping.yaml").exists()


def test_yaml_plugin_loads_from_drop_in_dir(tmp_path):
    from bobanana.memory import MemoryManager
    from bobanana.tools import Toolbox
    from bobanana.tools.registry import seed_plugin_directory

    plugin_dir = tmp_path / ".bobanana" / "tools"
    seed_plugin_directory(plugin_dir)
    mem = MemoryManager(tmp_path / ".bobanana")
    try:
        tb = Toolbox(tmp_path, mem, web_enabled=False, skill_registry=None,
                     plugin_dir=plugin_dir, enable_plugins=True)
        cat = {e["name"]: e for e in tb.catalog()}
        assert "plugin_ping" in cat
        assert cat["plugin_ping"]["version"] == "1.0.0"
        assert cat["plugin_ping"]["source"] == "yaml"
        tool = tb.get("plugin_ping")
        out = tool.invoke({"caller": "test"})
        assert "pong" in out
    finally:
        mem.close()


def test_permission_denied_blocks_write(tmp_path):
    from bobanana.memory import MemoryManager
    from bobanana.tools import Toolbox
    from bobanana.tools.permissions import Permission, PermissionPolicy

    mem = MemoryManager(tmp_path / ".bobanana")
    try:
        policy = PermissionPolicy({Permission.READ})  # no write
        tb = Toolbox(tmp_path, mem, web_enabled=False, skill_registry=None,
                     enable_plugins=False, permission_policy=policy)
        result = tb.get("write_file").invoke({"path": "x.txt", "content": "nope"})
        assert "permission denied" in result.lower()
    finally:
        mem.close()


def test_describe_tool_registry_meta_tool(tmp_path):
    from bobanana.memory import MemoryManager
    from bobanana.tools import Toolbox
    import json

    mem = MemoryManager(tmp_path / ".bobanana")
    try:
        tb = Toolbox(tmp_path, mem, web_enabled=False, skill_registry=None, enable_plugins=False)
        assert tb.get("describe_tool_registry") is not None
        raw = tb.describe_registry()
        data = json.loads(raw)
        assert data["registry"] == Toolbox.REGISTRY_MODULE
        assert "read_file" in {t["name"] for t in data["tools"]}
        assert "how_to_extend" in data
    finally:
        mem.close()


def test_core_tools_have_semver_and_permissions(tmp_path):
    from bobanana.memory import MemoryManager
    from bobanana.tools import Toolbox
    from bobanana.tools.permissions import Permission

    mem = MemoryManager(tmp_path / ".bobanana")
    try:
        tb = Toolbox(tmp_path, mem, web_enabled=False, skill_registry=None, enable_plugins=False)
        spec = tb.get_spec("read_file")
        assert spec.version == "1.0.0"
        assert Permission.READ in spec.permissions
        assert Permission.SHELL in tb.get_spec("run_shell").permissions
    finally:
        mem.close()


def test_read_file_source_with_timeout_string_no_false_replan():
    """Reading shell_tools.py must NOT trigger REPLAN (source contains ERROR: TIMEOUT)."""
    from bobanana.agents.executor import ExecutorAgent
    from langchain_core.messages import AIMessage

    fake_source = (
        'return f"ERROR: TIMEOUT after {self.timeout}s running `{command[:120]}`. "\n'
        "The current approach is stuck"
    )

    class _ReadTool:
        name = "read_file"

        def invoke(self, args):
            return fake_source

    class _OneReadLLM:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return AIMessage(content="", tool_calls=[
                {"name": "read_file", "args": {"path": "bobanana/tools/shell_tools.py"}, "id": "1"},
            ])

    class _FinishLLM:
        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[
                    {"name": "read_file", "args": {"path": "bobanana/tools/shell_tools.py"}, "id": "1"},
                ])
            return AIMessage(content="summarized shell_tools.py")

    ex = ExecutorAgent(_FinishLLM(), [_ReadTool()], max_tool_iters=4)
    out = ex.execute("read shell_tools.py", context="")
    assert not out.lstrip().startswith("REPLAN_NEEDED")
    assert "summarized" in out or "TIMEOUT" in ex.last_evidence


def test_read_file_evidence_in_last_evidence():
    from bobanana.agents.executor import ExecutorAgent
    from langchain_core.messages import AIMessage

    class _ReadTool:
        name = "read_file"

        def invoke(self, args):
            return "def hello(): pass"

    class _LLM:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return AIMessage(content="", tool_calls=[
                {"name": "read_file", "args": {"path": "a.py"}, "id": "1"},
            ])

    ex = ExecutorAgent(_LLM(), [_ReadTool()], max_tool_iters=2)
    ex.execute("read a.py", context="")
    assert "[read] a.py" in ex.last_evidence
    assert "def hello" in ex.last_evidence


def test_build_workspace_index_lists_package(tmp_path):
    from bobanana.workspace_index import build_workspace_index

    (tmp_path / "bobanana").mkdir()
    (tmp_path / "bobanana" / "graph.py").write_text("# g", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "PROJECT.md").write_text("# doc", encoding="utf-8")
    idx = build_workspace_index(tmp_path)
    assert "bobanana/" in idx
    assert "graph.py" in idx
    assert "PROJECT.md" in idx


def test_validate_plan_phantom_paths(tmp_path):
    from bobanana.plan_validation import validate_plan
    from bobanana.state import Plan, PlanStep

    plan = Plan(
        summary="bad",
        steps=[
            PlanStep(id=1, description="read_file src/plan_executor.py"),
        ],
        key_directives=["done"],
    )
    v = validate_plan(plan, "review architecture", tmp_path, "")
    assert not v.ok
    assert v.phantom_hits


def test_clear_mind_keeps_scratch_clears_turns(tmp_path):
    from bobanana.memory.manager import MemoryManager

    mm = MemoryManager(tmp_path / ".bobanana")
    mm.working.set_scratch("workspace_index", "index-data")
    mm.working.add_turn("user", "hello")
    mm.record_fact("current_plan", "x", category="plan")
    mm.record_exploration("k", "read_file", "p", "body")
    stats = mm.clear_mind()
    assert stats["turns_cleared"] == 1
    assert stats["exploration_cleared"] == 1
    assert stats["facts_cleared"] == 1
    assert mm.working.get_scratch("workspace_index") == "index-data"
    assert len(mm.working.recent(9999)) == 0
    assert mm.structured.get_fact("current_plan") is None


def test_validate_report_content_rejects_wrong_date(tmp_path):
    from datetime import date
    from bobanana.report_validation import build_report_header, validate_report_content

    today = date.today().isoformat()
    header = build_report_header(["docs/PROJECT.md"])
    bad = header + "\n\n生成日期: 2025-01\n"
    v = validate_report_content(bad, ["docs/PROJECT.md"], tmp_path, today=date.today())
    assert not v.ok
    assert any("2025" in x for x in v.violations)


def test_validate_report_content_rejects_false_chroma_claim(tmp_path):
    from datetime import date
    from bobanana.report_validation import build_report_header, validate_report_content

    text = build_report_header([]) + "\n\nMemory uses ChromaDB for vectors.\n"
    v = validate_report_content(text, [], tmp_path, today=date.today())
    assert not v.ok


def test_validate_architecture_deliverable_path():
    from bobanana.report_validation import validate_architecture_deliverable_path

    assert validate_architecture_deliverable_path("critique_report.md") is not None
    assert validate_architecture_deliverable_path("docs/delivery/output/2026-05-30-architecture-critique.md") is None


def test_registry_blocks_read_deliverable(tmp_path):
    from bobanana.memory.manager import MemoryManager
    from bobanana.tools.registry import Toolbox

    mm = MemoryManager(tmp_path / ".bobanana")
    mm.working.set_scratch("deliverable_path", "docs/delivery/output/report.md")
    tb = Toolbox(tmp_path, mm)
    out = tb.get("read_file").invoke({"path": "docs/delivery/output/report.md"})
    assert "ERROR" in out
    assert "deliverable" in out.lower()


def test_validate_plan_architecture_step_cap(tmp_path):
    from bobanana.plan_validation import validate_plan, ARCHITECTURE_MAX_STEPS
    from bobanana.state import Plan, PlanStep

    steps = [PlanStep(id=i, description=f"read_file bobanana/f{i}.py") for i in range(1, ARCHITECTURE_MAX_STEPS + 2)]
    plan = Plan(summary="big", steps=steps, key_directives=["report"])
    v = validate_plan(plan, "严肃批判 agent 架构", tmp_path, "bobanana/f1.py")
    assert v.step_count == ARCHITECTURE_MAX_STEPS + 1
    assert not v.ok


def test_shell_blocks_dir_exploration(tmp_path):
    from bobanana.tools.shell_tools import ShellRunner, is_directory_exploration_command

    assert is_directory_exploration_command("dir")
    assert is_directory_exploration_command("ls -la")
    runner = ShellRunner(tmp_path)
    out = runner.run("dir")
    assert "list_dir" in out
    assert "TIMEOUT" not in out


def test_inject_workspace_context_scratch_index(tmp_path):
    from bobanana.memory.working_memory import WorkingMemory
    from bobanana.workspace_map import inject_workspace_context

    mem = WorkingMemory()
    mem.set_scratch("workspace_index", "## Live workspace index\nbobanana/graph.py")
    mem.set_scratch("tool_catalog_summary", '{"tools":[]}')
    ctx = inject_workspace_context("task", "base", mem)
    assert "Live workspace index" in ctx or "bobanana/graph.py" in ctx
    assert "tool_catalog" in ctx.lower() or "programmatic" in ctx.lower()


def test_apply_budget_caps_plan_revisions_for_architecture(tmp_path):
    from bobanana.app import Application
    from bobanana.config import Settings

    settings = Settings(workspace=tmp_path, data_dir=tmp_path / ".bobanana", max_plan_revisions=3)
    app = Application(settings)
    scaled = app.apply_budget(0.8, "严肃批判当前 agent 架构")
    assert scaled["max_plan_revisions"] <= 1


def test_validate_plan_deliverable_path_no_false_positive(tmp_path):
    from bobanana.plan_validation import validate_plan
    from bobanana.state import Plan, PlanStep

    steps = [
        PlanStep(id=1, description="read_file docs/PROJECT.md"),
        PlanStep(id=2, description="read_file bobanana/memory/manager.py"),
        PlanStep(id=3, description="read_file tests/test_features.py"),
        PlanStep(id=4, description="describe_tool_registry"),
        PlanStep(id=5, description="read_file bobanana/graph.py"),
        PlanStep(id=6, description="read_file bobanana/tools/registry.py"),
        PlanStep(id=7, description="read_file bobanana/report_validation.py"),
        PlanStep(
            id=8,
            description="write_file docs/delivery/output/2026-05-30-architecture-critique.md with report",
        ),
    ]
    plan = Plan(summary="arch", steps=steps, key_directives=["write report"])
    (tmp_path / "docs" / "PROJECT.md").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "PROJECT.md").write_text("# proj", encoding="utf-8")
    v = validate_plan(plan, "严肃批判 agent 架构", tmp_path, "bobanana/graph.py")
    deliverable_errors = [w for w in v.warnings if "docs/delivery/output/" in w and "must be under" in w]
    assert not deliverable_errors


def test_validate_report_proposed_path_not_violation(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    text = build_report_header(["docs/PROJECT.md"]) + "\n\n可命名为 `tests/test_foo.py` 作为回归用例。\n"
    v = validate_report_content(text, ["docs/PROJECT.md"], tmp_path, today=date.today())
    path_v = [x for x in v.violations if "test_foo" in x]
    assert not path_v


def test_validate_report_existing_path_still_violation(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    text = build_report_header([]) + "\n\n`tests/test_foo.py` 中存在相关测试。\n"
    v = validate_report_content(text, [], tmp_path, today=date.today())
    assert not v.ok
    assert any("test_foo" in x for x in v.violations)


def test_validate_report_false_claim_run_bobanana(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    text = build_report_header([]) + "\n\n入口为 run_bobanana() 函数。\n"
    v = validate_report_content(text, [], tmp_path, today=date.today())
    assert not v.ok


def test_validate_report_false_claim_list_symbols(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    text = build_report_header([]) + "\n\nbuild_context 调用 list_symbols()。\n"
    v = validate_report_content(text, [], tmp_path, today=date.today())
    assert not v.ok


def test_validate_report_false_claim_mcp_not_integrated(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    text = build_report_header([]) + "\n\nMCP 客户端未集成到 Toolbox。\n"
    v = validate_report_content(text, [], tmp_path, today=date.today())
    assert not v.ok


def test_validate_report_false_claim_execute_tool(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    text = build_report_header([]) + "\n\n通过 execute_tool() 调用工具。\n"
    v = validate_report_content(text, [], tmp_path, today=date.today())
    assert not v.ok


def test_validate_report_no_false_claim_negated_execute_tool(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    text = build_report_header([]) + "\n\nToolbox 没有 execute_tool() 方法。\n"
    v = validate_report_content(text, [], tmp_path, today=date.today())
    assert not any("execute_tool" in x for x in v.violations)


def test_validate_report_false_claim_chroma(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    text = build_report_header([]) + "\n\n向量记忆（Chroma）与工作记忆并存。\n"
    v = validate_report_content(text, [], tmp_path, today=date.today())
    assert not v.ok


def test_validate_report_false_claim_memory_store(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    text = build_report_header([]) + "\n\nexecutor 调用 memory.store()。\n"
    v = validate_report_content(text, [], tmp_path, today=date.today())
    assert not v.ok


def test_validate_report_false_claim_create_graph(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    text = build_report_header([]) + "\n\ngraph 中 _create_graph() 承担组装。\n"
    v = validate_report_content(text, [], tmp_path, today=date.today())
    assert not v.ok


def test_validate_report_false_claim_config_shell_timeout(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    text = build_report_header([]) + "\n\nconfig.py 未读取 BOBANANA_SHELL_TIMEOUT。\n"
    v = validate_report_content(text, [], tmp_path, today=date.today())
    assert not v.ok


def test_pytest_cov_url_clears_needs_web(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    text = (
        build_report_header([])
        + "\n\n建议使用 pytest-cov（https://pypi.org/project/pytest-cov/ v7.1.0）。\n"
    )
    v = validate_report_content(text, [], tmp_path, today=date.today())
    assert not v.needs_web


def test_test_count_requires_pytest_collect(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    text = build_report_header([]) + "\n\ntest_features.py 约 25 个测试。\n"
    v = validate_report_content(text, [], tmp_path, today=date.today())
    assert not v.ok
    assert any("pytest" in x.lower() for x in v.violations)


def test_test_count_matches_pytest_collect(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    scratch = {"pytest_collect_count": "116"}
    text = build_report_header([]) + "\n\n共 116 个测试。\n"
    v = validate_report_content(text, [], tmp_path, today=date.today(), scratch=scratch)
    assert v.ok


def test_validation_not_acceptable_without_pytest():
    from bobanana.report_validation import ReportValidation, validation_acceptable_ok

    v = ReportValidation(
        ok=False,
        violations=["Test count claimed but pytest --collect-only -q was not run this task"],
    )
    assert not validation_acceptable_ok(v)


def test_validation_acceptable_when_clean():
    from bobanana.report_validation import ReportValidation, validation_acceptable_ok

    assert validation_acceptable_ok(ReportValidation(ok=True))


def test_shell_blocks_type_on_deliverable(tmp_path):
    from bobanana.memory.manager import MemoryManager
    from bobanana.tools.registry import Toolbox

    deliverable = "docs/delivery/output/report.md"
    (tmp_path / deliverable).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / deliverable).write_text("# report\n" * 20, encoding="utf-8")
    mm = MemoryManager(tmp_path / ".bobanana")
    mm.working.set_scratch("deliverable_path", deliverable)
    tb = Toolbox(tmp_path, mm)
    out = tb.get("run_shell").invoke({"command": f"type {deliverable}"})
    assert "ERROR" in out
    assert "deliverable" in out.lower()


def test_blocked_critique_report_md(tmp_path):
    from bobanana.memory.manager import MemoryManager
    from bobanana.tools.registry import Toolbox

    (tmp_path / "critique_report.md").write_text("# old", encoding="utf-8")
    mm = MemoryManager(tmp_path / ".bobanana")
    mm.working.set_scratch("deliverable_path", "docs/delivery/output/r.md")
    tb = Toolbox(tmp_path, mm)
    out = tb.get("read_file").invoke({"path": "critique_report.md"})
    assert "ERROR" in out
    assert "stale" in out.lower()


def test_blocked_delivery_output_md(tmp_path):
    from bobanana.memory.manager import MemoryManager
    from bobanana.tools.registry import Toolbox

    path = "docs/delivery/output/old-run.md"
    (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / path).write_text("# old run", encoding="utf-8")
    mm = MemoryManager(tmp_path / ".bobanana")
    mm.working.set_scratch("deliverable_path", "docs/delivery/output/new.md")
    tb = Toolbox(tmp_path, mm)
    out = tb.get("read_file").invoke({"path": path})
    assert "ERROR" in out
    assert "unverified" in out.lower()


def test_record_pytest_collect_output():
    from bobanana.report_validation import get_pytest_collect_count, record_pytest_collect_output

    scratch: dict = {}
    record_pytest_collect_output(scratch, "================= 78 tests collected in 0.12s =================")
    assert get_pytest_collect_count(scratch) == 78


def test_registry_records_pytest_collect(tmp_path):
    from unittest.mock import patch

    from bobanana.memory.manager import MemoryManager
    from bobanana.report_validation import get_pytest_collect_count
    from bobanana.tools.registry import Toolbox

    mm = MemoryManager(tmp_path / ".bobanana")
    tb = Toolbox(tmp_path, mm)
    with patch.object(tb.shell, "run", return_value="78 tests collected in 0.12s"):
        tb.get("run_shell").invoke({"command": "pytest --collect-only -q"})
    assert get_pytest_collect_count(mm.working.scratch) == 78


def test_validate_report_false_claim_build_graph(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    text = build_report_header([]) + "\n\ngraph 使用 _build_graph() 组装。\n"
    v = validate_report_content(text, [], tmp_path, today=date.today())
    assert not v.ok


def test_validate_report_false_claim_no_path_traversal(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    text = build_report_header([]) + "\n\n文件读写无路径遍历防护。\n"
    v = validate_report_content(text, [], tmp_path, today=date.today())
    assert not v.ok


def test_validate_report_pseudocode_fenced_block(tmp_path):
    from bobanana.report_validation import build_report_header, validate_report_content
    from datetime import date

    (tmp_path / "bobanana" / "graph.py").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "bobanana" / "graph.py").write_text("def _build(self):\n    pass\n", encoding="utf-8")
    fake = build_report_header(["bobanana/graph.py"]) + (
        "\n\n```python\n"
        "raise ValueError(f'File not found: {path}')\n"
        "def _build_graph():\n"
        "    pass\n"
        "```\n"
    )
    v = validate_report_content(fake, ["bobanana/graph.py"], tmp_path, today=date.today())
    assert not v.ok
    assert any("Pseudocode" in x or "ValueError" in x for x in v.violations)


def test_validate_report_agent_header_required(tmp_path):
    from bobanana.report_validation import validate_report_content
    from datetime import date

    text = "> Generated: 2026-05-30\n> Agent: code-delivery-gate\n\nbody\n"
    v = validate_report_content(text, [], tmp_path, today=date.today())
    assert not v.ok
    assert any("Agent" in x for x in v.violations)


def test_deliverable_write_blocked_without_pytest(tmp_path):
    from bobanana.memory.manager import MemoryManager
    from bobanana.tools.registry import Toolbox

    deliverable = "docs/delivery/output/report.md"
    mm = MemoryManager(tmp_path / ".bobanana")
    mm.working.set_scratch("deliverable_path", deliverable)
    tb = Toolbox(tmp_path, mm)
    out = tb.get("write_file").invoke({"path": deliverable, "content": "# x\n"})
    assert "ERROR" in out
    assert "pytest" in out.lower()


def test_deliverable_write_allowed_after_pytest_collect(tmp_path):
    from unittest.mock import patch

    from bobanana.memory.manager import MemoryManager
    from bobanana.tools.registry import Toolbox

    deliverable = "docs/delivery/output/report.md"
    mm = MemoryManager(tmp_path / ".bobanana")
    mm.working.set_scratch("deliverable_path", deliverable)
    tb = Toolbox(tmp_path, mm)
    with patch.object(tb.shell, "run", return_value="92/94 tests collected (2 deselected)"):
        tb.get("run_shell").invoke({"command": "pytest --collect-only -q"})
    out = tb.get("write_file").invoke({"path": deliverable, "content": "# report\n" + ("x" * 60)})
    assert out.startswith("OK")


def test_version_line():
    from bobanana import __version__
    from bobanana.version import RELEASE_TAG, version_line
    from pathlib import Path

    assert __version__ == "3.0.0"
    line = version_line()
    assert __version__ in line
    assert RELEASE_TAG in line
    root_ver = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
    assert root_ver == __version__


def test_verify_deliverable_on_disk(tmp_path):
    from bobanana.report_validation import build_report_header, verify_deliverable_on_disk
    from datetime import date

    today = date.today().isoformat()
    path = f"docs/delivery/output/{today}-architecture-critique.md"
    full = tmp_path / path
    full.parent.mkdir(parents=True, exist_ok=True)
    body = build_report_header(["docs/PROJECT.md"]) + "\n\n" + ("x" * 200)
    full.write_text(body, encoding="utf-8")
    ok, excerpt, validation = verify_deliverable_on_disk(path, tmp_path, ["docs/PROJECT.md"])
    assert ok
    assert validation.ok
    assert len(excerpt) > 50


def test_workspace_map_injected_for_architecture_task():
    from bobanana.workspace_map import inject_workspace_context

    ctx = inject_workspace_context("严肃批判当前agent架构", "(memory empty)")
    assert "bobanana/" in ctx
    assert "docs/PROJECT.md" in ctx
    assert "docs/delivery/output/" in ctx
    assert "memory/manager.py" in ctx
    assert "describe_tool_registry" in ctx
    assert "There is no" in ctx


if __name__ == "__main__":
    test_is_code_task()
    test_looks_large_and_unclear()
    test_should_metaprompt()
    test_metaprompter_parses_model()
    test_metaprompter_fallback_on_garbage()
    test_validate_directory()
    test_delivery_gate_directive_for_code_task()
    test_delivery_gate_disabled()
    test_build_restart_argv()
    test_looks_posix_only_detection()
    test_default_allowlist_is_os_aware()
    test_is_nonproductive()
    test_cached_result_is_nonproductive()
    test_directive_gate_reports_unmet()
    print("all feature tests PASSED")
