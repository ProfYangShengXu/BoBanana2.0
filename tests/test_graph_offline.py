"""Offline end-to-end test of the variant-ReAct graph using a stub LLM.

Runs the full plan -> plan_review -> execute -> exec_review -> finalize flow with
no network, asserting routing works, the tool actually writes a file, and memory
records the side-effect.
"""

import tempfile
from pathlib import Path

from langchain_core.messages import AIMessage

from bobanana.config import Settings
from bobanana.graph import CodingAgentGraph
from bobanana.memory import MemoryManager
from bobanana.state import Plan, PlanStep, ReviewResult


class _Struct:
    def __init__(self, schema):
        self.schema = schema

    def invoke(self, messages):
        if self.schema is Plan:
            return Plan(summary="stub plan", steps=[
                PlanStep(id=1, description="create hello.txt containing 'hi'"),
            ])
        return ReviewResult(approved=True, score=9, suggestions=[], rationale="looks good")


class FakeChat:
    """Minimal stand-in for ChatOpenAI."""

    def with_structured_output(self, schema, method=None):
        return _Struct(schema)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        text = " ".join(str(getattr(m, "content", "")) for m in messages)
        if "Summarize the completed" in text:
            return AIMessage(content="Done: created hello.txt.")
        # executor path: first turn -> tool call; after tool ran -> finish
        has_tool_result = any(type(m).__name__ == "ToolMessage" for m in messages)
        if not has_tool_result:
            return AIMessage(content="", tool_calls=[{
                "name": "write_file",
                "args": {"path": "hello.txt", "content": "hi"},
                "id": "call_1",
            }])
        return AIMessage(content="Wrote hello.txt with 'hi'.")


def test_graph_runs_offline():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        ws = Path(tmp)
        settings = Settings(workspace=ws, data_dir=ws / ".bobanana",
                            max_plan_revisions=1, max_exec_revisions=1, max_steps=4)
        settings.ensure_dirs()
        memory = MemoryManager(settings.data_dir)
        events: list[dict] = []
        graph = CodingAgentGraph(settings, FakeChat(), memory, on_event=events.append)

        result = graph.run("create hello.txt")

        assert result["done"] is True
        assert "hello.txt" in result["final_answer"] or result["final_answer"]
        assert (ws / "hello.txt").read_text() == "hi"
        assert any(e["kind"] == "final" for e in events)
        assert memory.structured.get_file("hello.txt") is not None
        memory.close()


if __name__ == "__main__":
    test_graph_runs_offline()
    print("test_graph_runs_offline PASSED")
