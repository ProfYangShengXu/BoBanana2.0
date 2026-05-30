"""Canonical workspace layout hints injected into planner/executor context.

Stops the agent from guessing paths like ``src/``, ``plan_executor.py``, or
inferring tools only from ``dir .bobanana\\tools``.
"""

from __future__ import annotations

from pathlib import Path

WORKSPACE_MAP = """\
## Workspace map (authoritative — do NOT guess other layouts)

| Path | Purpose |
|------|---------|
| `bobanana/` | **Main Python package** — app, graph, agents, tools, memory |
| `bobanana/app.py` | Application wiring |
| `bobanana/graph.py` | LangGraph orchestration |
| `bobanana/agents/` | planner, reviewer, executor, intent, directive_gate |
| `bobanana/tools/registry.py` | **Tool registry** (StructuredTool + plugins) |
| `bobanana/tools/plugin_registry.py` | YAML/Python drop-in plugins |
| `docs/PROJECT.md` | Architecture doc — **read this first** for architecture tasks |
| `tests/` | pytest suite |
| `.bobanana/tools/` | Drop-in plugin data (YAML/py), NOT the core registry code |
| `.bobanana/structured.db` | Runtime structured memory |

**There is no** `src/`, `agent/`, `plan_executor.py`, or `base_tool.py` in this repo.

**Tool discovery**: call `describe_tool_registry` or `/tools` — never infer from `dir` alone.
**File reads**: use `read_file` / `list_dir`, not `cat`/`type` shell hacks.
"""


def architecture_task_hint(user_request: str) -> str:
    """Return extra planner/executor hints for architecture review / critique tasks."""
    from datetime import date

    low = user_request.lower()
    keys = ("架构", "批判", "architecture", "critique", "review agent", "分析", "整体设计")
    if not any(k in low for k in keys):
        return ""
    today = date.today().isoformat()
    report_path = f"docs/delivery/output/{today}-architecture-critique.md"
    return (
        "\n\n## Task-specific planning rules (architecture / critique)\n"
        f"1. First step: `read_file docs/PROJECT.md`.\n"
        "2. Include `read_file bobanana/memory/manager.py` and `read_file tests/test_features.py`.\n"
        "3. Call `describe_tool_registry` once OR read `bobanana/tools/registry.py`.\n"
        "4. Read core modules under `bobanana/` (graph, agents, tools).\n"
        f"5. Final step: `write_file {report_path}` — use today's date ({today}), never 2025-01 or other stale dates.\n"
        "6. Do NOT `read_file` the deliverable before writing; compose from sources read in earlier steps.\n"
        "7. Do NOT write `critique_report.md` at repo root.\n"
        f"8. Keep plan ≤{8} steps.\n"
    )


def inject_workspace_context(
    user_request: str,
    base_context: str,
    memory=None,
) -> str:
    """Inject static map + scratch index/catalog + memory context."""
    hint = architecture_task_hint(user_request)
    parts: list[str] = []
    if memory is not None:
        wm = getattr(memory, "working", memory)
        live = wm.get_scratch("workspace_index")
        if live:
            parts.append(live)
        catalog = wm.get_scratch("tool_catalog_summary")
        if catalog:
            parts.append(
                "## Tool catalog (programmatic — use this, not dir .bobanana/tools)\n"
                + catalog[:1500]
            )
    parts.append(WORKSPACE_MAP)
    if hint:
        parts.append(hint)
    parts.append(base_context)
    return "\n\n".join(parts)
