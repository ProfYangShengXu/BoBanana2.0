"""Offline tests for the skills registry, web tools, and MCP graceful-degrade."""

import tempfile
from pathlib import Path

from bobanana.mcp import McpManager
from bobanana.memory import MemoryManager
from bobanana.skills import SkillRegistry
from bobanana.tools import Toolbox

SKILL_MD = """\
---
name: demo-skill
description: A demo skill for testing discovery.
---

# Demo
Run `demo --help`.
"""


def test_skill_discovery_and_tools():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        skill_dir = root / "skills" / "demo-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")

        reg = SkillRegistry([root / "skills"], external_dir=root / ".external")
        names = [s.name for s in reg.list()]
        assert "demo-skill" in names
        assert reg.get("demo-skill") is not None
        assert "A demo skill" in reg.get("demo-skill").description
        body = reg.read("demo-skill")
        assert "Run `demo --help`" in body
        assert reg.read("nope").startswith("ERROR")

        memory = MemoryManager(root / ".bobanana")
        tb = Toolbox(root, memory, skill_registry=reg, web_enabled=True, mcp_tools=[])
        tool_names = [t.name for t in tb.tools]
        for expected in ["list_skills", "use_skill", "load_skill_repo",
                         "web_search", "fetch_url", "clone_repo", "run_shell"]:
            assert expected in tool_names, f"missing tool {expected}"

        assert "demo-skill" in tb.get("list_skills").invoke({})
        assert tb.get("web_search").invoke({"query": ""}).startswith("ERROR")
        assert tb.get("fetch_url").invoke({"url": "ftp://x"}).startswith("ERROR")
        memory.close()


def test_mcp_no_config_graceful():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        mgr = McpManager(Path(tmp) / "missing.json")
        tools, status = mgr.load()
        assert tools == []
        assert "skipped" in status


if __name__ == "__main__":
    test_skill_discovery_and_tools()
    test_mcp_no_config_graceful()
    print("test_skills_offline PASSED")
