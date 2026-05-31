"""Build the LangChain tool set, wired to workspace + memory + skills + web + MCP.

Core tools register here with semver + permissions. Drop-in plugins load from
``<data_dir>/tools/`` (``.bobanana/tools/``) as YAML manifests or ``@register_tool``
Python modules. Use ``describe_tool_registry`` for introspection — do NOT infer
the registry by scanning directories.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import List, Optional, Set

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..logging_setup import get_logger
from ..memory import MemoryManager
from ..skills import SkillRegistry
from .file_tools import FileOps
from .permissions import Permission, PermissionPolicy, format_permissions
from .plugin_registry import (
    PluginContext,
    PluginLoader,
    ToolSpec,
    spec_for_core,
    wrap_with_permissions,
)
from .shell_tools import ShellRunner, is_shell_reading_file, shell_environment_hint
from .web_tools import WebTools

log = get_logger("tools")

_CORE_VERSION = "1.0.0"

# First token of read-only shell commands whose results are safe to cache.
_READONLY_SHELL = {
    "dir", "type", "where", "findstr", "tree", "more",
    "ls", "cat", "find", "rg", "grep", "head", "tail", "pwd",
}

_CACHED_PREFIX = (
    "[cached] 已探索过（结果取自结构化记忆），请勿重复调用相同探索；"
    "如目标已变更请先执行写操作再探索。\n"
)

_TEMPLATES_DIR = Path(__file__).resolve().parent / "plugin_templates"


class ReadArgs(BaseModel):
    path: str = Field(description="File path relative to the workspace root.")


class WriteArgs(BaseModel):
    path: str = Field(description="File path relative to the workspace root.")
    content: str = Field(description="Full file content to write.")


class ListArgs(BaseModel):
    path: str = Field(default=".", description="Directory path relative to workspace root.")


class ShellArgs(BaseModel):
    command: str = Field(description="Shell command to run (first token must be allowlisted).")


class SearchArgs(BaseModel):
    query: str = Field(description="Search query for the web.")
    max_results: int = Field(default=5, description="Max number of results.")


class FetchArgs(BaseModel):
    url: str = Field(description="Absolute http(s) URL to fetch.")


class CloneArgs(BaseModel):
    git_url: str = Field(description="Git URL of the repo to clone into the workspace.")
    dest: str = Field(default="", description="Optional destination folder name under external/.")


class UseSkillArgs(BaseModel):
    name: str = Field(description="Name of the skill to load (see list_skills).")


class LoadSkillRepoArgs(BaseModel):
    git_url: str = Field(description="Git URL of an external skill repository to register.")
    name: str = Field(default="", description="Optional folder name for the cloned repo.")


class Toolbox:
    REGISTRY_MODULE = "bobanana.tools.registry.Toolbox"

    def __init__(
        self,
        workspace: Path,
        memory: MemoryManager,
        shell_timeout: int = 60,
        skill_registry: Optional[SkillRegistry] = None,
        web_enabled: bool = True,
        mcp_tools: Optional[List] = None,
        exploration_cache: bool = True,
        *,
        plugin_dir: Optional[Path] = None,
        enable_plugins: bool = True,
        permission_policy: Optional[PermissionPolicy] = None,
        turn_journal=None,
    ) -> None:
        self.workspace = workspace
        self.files = FileOps(workspace)
        self.shell = ShellRunner(workspace, timeout=shell_timeout)
        self.memory = memory
        self.skills = skill_registry
        self.web = WebTools(workspace, memory) if web_enabled else None
        self._mcp_tools = list(mcp_tools or [])
        self._cache_enabled = exploration_cache
        self._enable_plugins = enable_plugins
        self._plugin_dir = plugin_dir or (workspace / ".bobanana" / "tools")
        self._policy = permission_policy or PermissionPolicy()
        self._turn_journal = turn_journal
        self._specs: dict[str, ToolSpec] = {}
        self._plugin_loader: PluginLoader | None = None
        self._tools = self._build()

    # ----- exploration cache helpers -----
    def _cache_get(self, key: str) -> str | None:
        if not self._cache_enabled:
            return None
        hit = self.memory.recall_exploration(key)
        if hit is not None:
            log.info("exploration cache hit: %s", key)
            return _CACHED_PREFIX + hit
        return None

    def _cache_put(self, key: str, tool: str, args: str, result: str) -> None:
        if not self._cache_enabled:
            return
        if result.lstrip().startswith("ERROR") or not result.strip():
            return
        self.memory.record_exploration(key, tool, args, result)

    def _invalidate_cache(self, reason: str) -> None:
        if not self._cache_enabled:
            return
        removed = self.memory.invalidate_exploration()
        if removed:
            log.info("exploration cache invalidated (%s): %d entr(ies) cleared", reason, removed)

    @property
    def tools(self) -> List[StructuredTool]:
        return self._tools

    @property
    def plugin_dir(self) -> Path:
        return self._plugin_dir

    @property
    def permission_policy(self) -> PermissionPolicy:
        return self._policy

    def get(self, name: str) -> StructuredTool | None:
        for t in self._tools:
            if getattr(t, "name", None) == name:
                return t
        return None

    def get_spec(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def reload_plugins(self) -> str:
        """Rescan ``.bobanana/tools/`` and rebuild the tool list (hot reload)."""
        self._tools = self._build()
        report = self._plugin_loader.report if self._plugin_loader else None
        if report is None:
            return "plugins disabled"
        return f"reloaded: {len(report.loaded)} plugin(s), errors={len(report.errors)}"

    def describe_registry(self) -> str:
        """Machine-readable registry introspection — prefer this over ``dir`` scans."""
        cat = self.catalog()
        report = self._plugin_loader.report if self._plugin_loader else None
        payload = {
            "registry": self.REGISTRY_MODULE,
            "plugin_dir": str(self._plugin_dir),
            "plugin_dir_exists": self._plugin_dir.is_dir(),
            "plugins_enabled": self._enable_plugins,
            "granted_permissions": format_permissions(self._policy.granted),
            "tool_count": len(cat),
            "tools": cat,
            "plugin_load": {
                "loaded": report.loaded if report else [],
                "skipped": report.skipped if report else [],
                "errors": report.errors if report else [],
            },
            "how_to_extend": (
                "Drop *.yaml or *.py into plugin_dir; see README.md there. "
                "Do NOT infer tools from directory listing alone — use this tool or /tools."
            ),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def catalog(self) -> list[dict]:
        out: list[dict] = []
        for t in self._tools:
            name = getattr(t, "name", "?")
            spec = self._specs.get(name) or getattr(t, "_bobanana_spec", None)
            if spec is None:
                out.append({
                    "name": name,
                    "description": getattr(t, "description", "") or "",
                    "source": "unknown",
                    "version": "0.0.0",
                    "permissions": "",
                    "origin": "",
                    "has_schema": getattr(t, "args_schema", None) is not None,
                })
                continue
            out.append({
                "name": name,
                "description": spec.description or getattr(t, "description", "") or "",
                "source": spec.source,
                "version": spec.version,
                "permissions": format_permissions(spec.permissions),
                "origin": spec.origin,
                "handler": spec.handler,
                "has_schema": getattr(t, "args_schema", None) is not None,
            })
        return out

    def _register(
        self,
        func,
        spec: ToolSpec,
        args_schema: type[BaseModel] | None = None,
    ) -> StructuredTool:
        if spec.name in self._specs:
            raise ValueError(f"duplicate tool: {spec.name}")
        kwargs = {"func": func, "name": spec.name, "description": spec.description}
        if args_schema is not None:
            kwargs["args_schema"] = args_schema
        tool = StructuredTool.from_function(**kwargs)
        tool = wrap_with_permissions(tool, spec, self._policy)
        self._specs[spec.name] = spec
        setattr(tool, "_bobanana_spec", spec)
        return tool

    # ----- file / shell (with memory side-effects + exploration cache) -----
    def _read(self, path: str) -> str:
        from ..report_validation import is_blocked_md_read

        blocked = is_blocked_md_read(path, self.memory.working.scratch)
        if blocked:
            return blocked
        key = f"read_file:{path}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        result = self.files.read_file(path)
        self._cache_put(key, "read_file", path, result)
        return result

    def _write(self, path: str, content: str) -> str:
        from ..report_validation import deliverable_write_blocked

        blocked = deliverable_write_blocked(self.memory.working.scratch, path)
        if blocked:
            return blocked
        if self._turn_journal is not None:
            self._turn_journal.record_file_before_write(path, self.workspace, self.files)
        result = self.files.write_file(path, content)
        if result.startswith("OK"):
            summary = content.strip().splitlines()[0][:120] if content.strip() else "(empty)"
            self.memory.record_file(path, summary=summary, lines=self.files.line_count(path))
            self.memory.record_fact(f"file:{path}", summary, category="file")
            if self._turn_journal is not None:
                self._turn_journal.record_structured_key(f"file:{path}")
            self._invalidate_cache("write_file")
        return result

    def _list(self, path: str = ".") -> str:
        key = f"list_dir:{path}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        result = self.files.list_dir(path)
        self._cache_put(key, "list_dir", path, result)
        return result

    def _run_shell(self, command: str) -> str:
        deliverable = self.memory.working.get_scratch("deliverable_path")
        if deliverable and is_shell_reading_file(command, deliverable):
            return (
                "ERROR: do not use run_shell to read the deliverable (type/cat/findstr) — "
                "compose the report from sources already read and write_file directly; "
                "use read_file only after writing for verification in remedial steps."
            )
        first = command.strip().split()[0].strip('"').lower() if command.strip() else ""
        readonly = first in _READONLY_SHELL
        if readonly:
            key = f"shell:{command.strip()}"
            cached = self._cache_get(key)
            if cached is not None:
                return cached
        result = self.shell.run(command)
        if "pytest" in command.lower() and "--collect-only" in command.lower():
            from ..report_validation import record_pytest_collect_output

            record_pytest_collect_output(self.memory.working.scratch, result)
        if readonly:
            self._cache_put(key, "run_shell", command.strip(), result)
            return result
        if not result.lstrip().startswith("ERROR"):
            self._invalidate_cache("run_shell(write)")
        return result

    def _list_skills(self) -> str:
        if not self.skills:
            return "ERROR: skills are not enabled"
        items = self.skills.list()
        if not items:
            return "(no skills discovered)"
        return "\n".join(f"- {s.name}: {s.description}" for s in items)

    def _use_skill(self, name: str) -> str:
        if not self.skills:
            return "ERROR: skills are not enabled"
        return self.skills.read(name)

    def _load_skill_repo(self, git_url: str, name: str = "") -> str:
        if not self.skills:
            return "ERROR: skills are not enabled"
        return self.skills.clone_repo(git_url, name or None)

    def _build(self) -> List[StructuredTool]:
        self._specs.clear()
        tools: List[StructuredTool] = []

        tools.append(self._register(
            self._read,
            spec_for_core("read_file", "Read a text file from the workspace and return its content.",
                          {Permission.READ}, _CORE_VERSION),
            ReadArgs,
        ))
        tools.append(self._register(
            self._write,
            spec_for_core("write_file", "Create or overwrite a file with the given content. Records it in memory.",
                          {Permission.WRITE}, _CORE_VERSION),
            WriteArgs,
        ))
        tools.append(self._register(
            self._list,
            spec_for_core("list_dir", "List files and directories under a workspace path.",
                          {Permission.READ}, _CORE_VERSION),
            ListArgs,
        ))
        shell_desc = (
            "Run an allowlisted shell command (tests, build, git, agent-reach CLI, etc.). "
            + shell_environment_hint(self.shell.allowlist)
        )
        tools.append(self._register(
            self._run_shell,
            spec_for_core("run_shell", shell_desc, {Permission.SHELL}, _CORE_VERSION),
            ShellArgs,
        ))

        if self.skills is not None:
            tools.append(self._register(
                self._list_skills,
                spec_for_core("list_skills", "List external skills available to adapt (name + description).",
                              {Permission.READ}, _CORE_VERSION),
            ))
            tools.append(self._register(
                self._use_skill,
                spec_for_core("use_skill", "Load a skill's SKILL.md instructions to follow (e.g. agent-reach). "
                              "After reading, use run_shell to invoke the skill's CLI.",
                              {Permission.READ}, _CORE_VERSION),
                UseSkillArgs,
            ))
            tools.append(self._register(
                self._load_skill_repo,
                spec_for_core("load_skill_repo", "Clone an external skill git repo and register its skills.",
                              {Permission.NETWORK, Permission.ADMIN}, _CORE_VERSION),
                LoadSkillRepoArgs,
            ))

        if self.web is not None:
            tools.append(self._register(
                self.web.web_search,
                spec_for_core("web_search", "Search the web (DuckDuckGo, no API key) and return top results.",
                              {Permission.NETWORK}, _CORE_VERSION),
                SearchArgs,
            ))
            tools.append(self._register(
                self.web.fetch_url,
                spec_for_core("fetch_url", "Fetch a web page or raw file URL and return readable text.",
                              {Permission.NETWORK}, _CORE_VERSION),
                FetchArgs,
            ))
            tools.append(self._register(
                self.web.clone_repo,
                spec_for_core("clone_repo", "Git-clone an external repo into the workspace and index it into memory.",
                              {Permission.NETWORK, Permission.WRITE}, _CORE_VERSION),
                CloneArgs,
            ))

        # Meta tool: introspection without filesystem guessing.
        tools.append(self._register(
            self.describe_registry,
            spec_for_core(
                "describe_tool_registry",
                "Return JSON catalog of ALL registered tools (core + plugins + MCP): names, semver, "
                "permissions, origins. Use this instead of scanning directories to discover tools.",
                {Permission.READ},
                _CORE_VERSION,
            ),
        ))

        if self._enable_plugins:
            ctx = PluginContext(workspace=self.workspace, shell=self.shell, memory=self.memory)
            self._plugin_loader = PluginLoader(self._plugin_dir, ctx)
            plugin_tools = self._plugin_loader.scan()
            for pt in plugin_tools:
                pspec = getattr(pt, "_bobanana_spec", None) or self._plugin_loader.specs.get(pt.name)
                if pspec and pt.name not in self._specs:
                    tools.append(wrap_with_permissions(pt, pspec, self._policy))
                    self._specs[pt.name] = pspec
            log.info("plugins: dir=%s loaded=%d errors=%d",
                     self._plugin_dir, len(self._plugin_loader.report.loaded),
                     len(self._plugin_loader.report.errors))
        else:
            self._plugin_loader = None

        for mt in self._mcp_tools:
            mname = getattr(mt, "name", "?")
            if mname in self._specs:
                continue
            mspec = ToolSpec(
                name=mname,
                description=getattr(mt, "description", "") or "",
                version="0.0.0",
                permissions={Permission.NETWORK},
                source="mcp",
                origin="mcp.json",
                handler="mcp",
            )
            tools.append(wrap_with_permissions(mt, mspec, self._policy))
            self._specs[mname] = mspec

        return tools


def seed_plugin_directory(plugin_dir: Path) -> None:
    """Copy starter manifests into ``.bobanana/tools/`` on first run."""
    plugin_dir.mkdir(parents=True, exist_ok=True)
    readme = plugin_dir / "README.md"
    if readme.exists():
        return
    if not _TEMPLATES_DIR.is_dir():
        readme.write_text(
            "# Tool plugins\n\nDrop `*.yaml` or `*.py` (@register_tool) here.\n",
            encoding="utf-8",
        )
        return
    for item in _TEMPLATES_DIR.iterdir():
        dest = plugin_dir / item.name
        if item.is_file() and not dest.exists():
            shutil.copy2(item, dest)
    log.info("seeded plugin directory: %s", plugin_dir)
