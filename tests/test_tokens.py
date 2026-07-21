"""Tests for the token optimisation P0 deliverable:
- MessageLengthMonitor
- BudgetController
- TokenUsageTracker integration
- executor.py message history summarisation helpers
"""

from __future__ import annotations

from bobanana.telemetry.tokens import (
    BudgetController,
    MessageLengthMonitor,
    TokenUsageTracker,
)
from bobanana.agents.executor import _should_summarise, _summarise_history

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


# ===================================================================
# MessageLengthMonitor
# ===================================================================

class TestMessageLengthMonitor:
    def test_empty_initial_state(self):
        m = MessageLengthMonitor()
        assert m.iteration_count == 0
        assert m.total_tokens == 0
        assert m.last is None
        assert "no iterations" in m.report()

    def test_record_single_iteration(self):
        m = MessageLengthMonitor()
        rec = m.record_iteration(100, 50, inp_chars=500, out_chars=200)
        assert rec.iteration == 1
        assert rec.input_tokens == 100
        assert rec.output_tokens == 50
        assert rec.total_tokens == 150
        assert m.iteration_count == 1
        assert m.total_input_tokens == 100
        assert m.total_output_tokens == 50
        assert m.total_tokens == 150
        assert m.last is rec

    def test_record_multiple_iterations(self):
        m = MessageLengthMonitor()
        m.record_iteration(10, 5)
        m.record_iteration(20, 10)
        m.record_iteration(30, 15)
        assert m.iteration_count == 3
        assert m.total_input_tokens == 60
        assert m.total_output_tokens == 30
        assert m.total_tokens == 90
        assert m.last is not None and m.last.iteration == 3

    def test_max_history_eviction(self):
        m = MessageLengthMonitor(max_history=3)
        for i in range(5):
            m.record_iteration(10, 5)
        assert m.iteration_count == 3  # only last 3 kept
        assert m.last is not None and m.last.iteration == 5

    def test_reset(self):
        m = MessageLengthMonitor()
        m.record_iteration(10, 5)
        m.reset()
        assert m.iteration_count == 0
        assert m.total_tokens == 0
        assert m.last is None

    def test_report_format(self):
        m = MessageLengthMonitor()
        m.record_iteration(100, 50)
        report = m.report()
        assert "Iterations: 1" in report
        assert "Total input tokens:  100" in report
        assert "Total output tokens: 50" in report


# ===================================================================
# BudgetController
# ===================================================================

class TestBudgetController:
    def test_empty_budgets(self):
        c = BudgetController()
        assert "no budgets" in c.report()
        result = c.record("executor", 100)
        assert result["breached"] is False

    def test_budget_not_breached(self):
        c = BudgetController(budgets={"executor": 1000})
        result = c.record("executor", 100)
        assert result["used"] == 100
        assert result["budget"] == 1000
        assert result["breached"] is False
        assert c.is_breached("executor") is False

    def test_budget_breached(self):
        alerts = []
        c = BudgetController(budgets={"executor": 150}, on_alert=lambda cat, used, lim: alerts.append((cat, used, lim)))
        c.record("executor", 100)
        assert not alerts
        result = c.record("executor", 60)  # total = 160 >= 150
        assert result["breached"] is True
        assert c.is_breached("executor") is True
        assert len(alerts) == 1
        assert alerts[0][0] == "executor"

    def test_alert_only_once(self):
        alerts = []
        c = BudgetController(budgets={"executor": 100}, on_alert=lambda cat, used, lim: alerts.append((cat, used, lim)))
        c.record("executor", 100)  # breach
        assert len(alerts) == 1
        c.record("executor", 50)   # still over, but no new alert
        assert len(alerts) == 1

    def test_set_budget_updates_limit_and_resets_alert(self):
        alerts = []
        c = BudgetController(budgets={"executor": 100}, on_alert=lambda cat, used, lim: alerts.append((cat, used, lim)))
        c.record("executor", 150)
        assert len(alerts) == 1
        # Raise budget so it's no longer breached
        c.set_budget("executor", 200)
        assert c.is_breached("executor") is False
        # Now record more to breach again
        c.record("executor", 60)  # total = 210 >= 200
        assert len(alerts) == 2

    def test_zero_limit_disabled(self):
        c = BudgetController(budgets={"executor": 0})
        c.record("executor", 999999)
        assert c.is_breached("executor") is False

    def test_negative_limit_clamped(self):
        c = BudgetController(budgets={"executor": -5})
        assert c._budgets["executor"] == 0

    def test_reset_category(self):
        c = BudgetController(budgets={"executor": 100, "planner": 100})
        c.record("executor", 150)
        c.record("planner", 50)
        assert c.is_breached("executor") is True
        c.reset("executor")
        assert c.is_breached("executor") is False
        assert c.usage("executor") == 0
        assert c.usage("planner") == 50  # untouched

    def test_reset_all(self):
        c = BudgetController(budgets={"executor": 100, "planner": 100})
        c.record("executor", 150)
        c.record("planner", 150)
        c.reset()
        assert c.usage("executor") == 0
        assert c.usage("planner") == 0
        assert c.is_breached("executor") is False

    def test_report_format(self):
        c = BudgetController(budgets={"executor": 1000, "planner": 500})
        c.record("executor", 100)
        c.record("planner", 600)  # breached
        report = c.report()
        assert "executor" in report
        assert "planner" in report
        assert "BREACHED" in report


# ===================================================================
# TokenUsageTracker integration
# ===================================================================

class TestTokenUsageTrackerIntegration:
    def test_record_updates_monitor_and_budget(self):
        t = TokenUsageTracker(budgets={"total": 1000})
        t.record("sess1", "task1", 100, 50)
        assert t.monitor.iteration_count == 1
        assert t.monitor.total_tokens == 150
        assert t.budget.usage("total") == 150

    def test_alert_callback_fires_on_breach(self):
        alerts = []
        t = TokenUsageTracker(budgets={"total": 100},
                              on_budget_alert=lambda *a: alerts.append(a))
        t.record("sess1", "task1", 80, 40)  # 120 >= 100
        assert alerts and alerts[0][0] == "total"
        assert t.budget.is_breached("total")

    def test_multiple_records(self):
        t = TokenUsageTracker()
        t.record("sess1", "task1", 10, 5)
        t.record("sess1", "task1", 20, 10)
        assert t.monitor.iteration_count == 2
        assert t.monitor.total_input_tokens == 30
        assert t.monitor.total_output_tokens == 15
        assert t.global_totals.input_tokens == 30
        assert t.global_totals.output_tokens == 15


# ===================================================================
# Executor message history summarisation
# ===================================================================

class TestExecutorSummarisation:
    def test_should_summarise_false_when_empty(self):
        assert _should_summarise([], max_before=5) is False

    def test_should_summarise_false_when_below_threshold(self):
        msgs = [HumanMessage(content="hi"), AIMessage(content="hello")]
        assert _should_summarise(msgs, max_before=5) is False

    def test_should_summarise_true_when_above_threshold(self):
        msgs = [HumanMessage(content=str(i)) for i in range(10)]
        assert _should_summarise(msgs, max_before=5) is True

    def test_should_summarise_ignores_system_messages(self):
        msgs = [SystemMessage(content="sys")] + [HumanMessage(content=str(i)) for i in range(10)]
        assert _should_summarise(msgs, max_before=5) is True

    def test_should_summarise_false_with_system_only(self):
        msgs = [SystemMessage(content="sys"), SystemMessage(content="sys2")]
        assert _should_summarise(msgs, max_before=5) is False

    def test_summarise_basic(self):
        msgs = [
            SystemMessage(content="system prompt"),
            HumanMessage(content="step 1"),
            AIMessage(content="tool call 1"),
            ToolMessage(content="result 1", tool_call_id="1"),
            HumanMessage(content="step 2"),
            AIMessage(content="tool call 2"),
            ToolMessage(content="result 2", tool_call_id="2"),
            HumanMessage(content="step 3"),
            AIMessage(content="tool call 3"),
            ToolMessage(content="result 3", tool_call_id="3"),
        ]
        result = _summarise_history(msgs, keep=3)
        # Should have: system + summary + last 3 non-system
        assert len(result) == 5  # 1 system + 1 summary + 3 recent
        assert isinstance(result[0], SystemMessage)
        assert isinstance(result[1], SystemMessage)  # summary
        assert result[1].content.startswith("[summarised history] ")
        # Last 3 should be the most recent messages
        assert isinstance(result[-3], HumanMessage)
        assert isinstance(result[-2], AIMessage)
        assert isinstance(result[-1], ToolMessage)

    def test_summarise_below_keep_threshold(self):
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="hi"),
            AIMessage(content="hello"),
        ]
        result = _summarise_history(msgs, keep=5)
        # Nothing to summarise — should return as-is
        assert len(result) == 3
        assert result[0].content == "sys"

    def test_summarise_never_orphans_leading_tool_message(self):
        """The kept tail must not begin with a ToolMessage — that orphan triggers an
        OpenAI 400 ('tool' must follow a message with 'tool_calls')."""
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="a"),
            AIMessage(content="b"),
            ToolMessage(content="c", tool_call_id="1"),
            HumanMessage(content="d"),
        ]
        result = _summarise_history(msgs, keep=2)
        # keep=2 would slice [Tool(c), Human(d)] (orphan tool). Boundary advances past
        # the tool message, so recent collapses to [Human(d)].
        assert isinstance(result[0], SystemMessage)  # original system prompt
        assert isinstance(result[1], SystemMessage)  # summary
        non_system = [m for m in result if not isinstance(m, SystemMessage)]
        assert non_system and not isinstance(non_system[0], ToolMessage)
        assert result[-1].content == "d"

    def test_summarise_keeps_tool_call_pairing_valid(self):
        """Regression for the 400 crash: an alternating AI(tool_calls)/Tool stream
        must summarise into an API-valid sequence (every ToolMessage preceded by an
        AIMessage that carries tool_calls)."""
        msgs: list = [SystemMessage(content="system prompt")]
        for i in range(8):
            msgs.append(AIMessage(content="", tool_calls=[
                {"name": "read_file", "args": {"path": f"f{i}.py"}, "id": f"c{i}"}]))
            msgs.append(ToolMessage(content=f"contents {i}", tool_call_id=f"c{i}"))
        result = _summarise_history(msgs, keep=5)
        # Validate: every ToolMessage sits inside a region opened by an AI(tool_calls).
        in_tool_region = False
        for m in result:
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                in_tool_region = True
            elif isinstance(m, ToolMessage):
                assert in_tool_region, "orphan ToolMessage would 400 the API"
            else:
                in_tool_region = False

    def test_summarise_preserves_system_messages(self):
        msgs = (
            [SystemMessage(content="sys1"), SystemMessage(content="sys2")]
            + [HumanMessage(content=str(i)) for i in range(10)]
        )
        result = _summarise_history(msgs, keep=3)
        # Both system messages should be preserved
        assert isinstance(result[0], SystemMessage)
        assert isinstance(result[1], SystemMessage)
        assert result[0].content == "sys1"
        assert result[1].content == "sys2"

    def test_summarise_truncates_long_content(self):
        """Very long individual messages should be truncated in the summary."""
        long_content = "x" * 2000
        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content=long_content),
            AIMessage(content="ok"),
            ToolMessage(content="done", tool_call_id="1"),
        ]
        result = _summarise_history(msgs, keep=1)
        # The summary should contain the truncated version
        summary = result[1]  # second message is the summary
        assert isinstance(summary, SystemMessage)
        assert "(+1500 chars)" in summary.content  # 2000 - 500 = 1500
