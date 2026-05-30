"""Runtime configuration loaded from environment / .env."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Load .env from project root (parent of bobanana package), not cwd.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)


def _env(key: str, default: str | None = None) -> str | None:
    val = os.getenv(key)
    return val if val not in (None, "") else default


def _env_int(key: str, default: int) -> int:
    raw = _env(key)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = _env(key)
    try:
        return float(raw) if raw is not None else default
    except ValueError:
        return default


def _normalize_base_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.rstrip("/")
    if "deepseek.com" in url.lower() and not url.endswith("/v1"):
        return url + "/v1"
    return url


def _env_bool(key: str, default: bool) -> bool:
    raw = _env(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class Settings(BaseModel):
    """Central settings. Construct via :meth:`load`."""

    # LLM
    api_key: str | None = None
    base_url: str | None = None
    model: str = "gpt-4o-mini"
    temperature: float = 0.1  # global fallback; per-role tiers live in llm.ROLE_TEMPERATURES

    # Review loops (these act as the UPPER bound / ceiling; the intent layer scales
    # the effective budget down for small tasks via scaled_budget(), and each review
    # rejection ratchets the per-step budget back UP toward this ceiling).
    max_plan_revisions: int = 3
    max_exec_revisions: int = 3
    max_steps: int = 20
    max_tool_iters: int = 24  # per-step ReAct tool budget (failed/cached calls don't count)
    max_directive_revisions: int = 3  # loops back to satisfy unmet key_directives
    shell_timeout: int = 120  # seconds; a command exceeding this triggers a replan

    # Interruptibility
    task_timeout: float = 0.0  # whole-task wall-clock seconds (0 = disabled); on timeout the
                               # run is interrupted at the next node boundary and awaits the user
    llm_timeout: int = 90  # per-LLM-call seconds; bounds each node so timeouts are detected
    enable_checkpoints: bool = True  # MemorySaver checkpoints enable resume/rollback

    # Intent layer: LLM sizes the task (0=greeting .. 1=large refactor) and decides
    # whether meta-prompting is worthwhile; the budget is scaled accordingly.
    enable_intent: bool = True

    # Exploration cache (reuse read_file/list_dir/read-only shell results)
    enable_exploration_cache: bool = True

    # Observability
    log_level: str = "INFO"

    # LLM structured output: auto | json_schema | json_mode | function_calling
    structured_output_method: str = "auto"

    # Skills / MCP / web
    enable_web_tools: bool = True
    skill_dirs: List[Path] = Field(default_factory=list)
    mcp_config: Path = Path.cwd() / "mcp.json"
    agent_reach_repo: str = "https://github.com/Panniantong/Agent-Reach.git"

    # Meta-prompting & delivery gate
    enable_metaprompt: bool = True
    enable_delivery_gate: bool = True
    delivery_gate_skill: str = "code-delivery-gate"

    # Tool plugins & permissions
    enable_tool_plugins: bool = True
    tool_permission_names: List[str] = Field(
        default_factory=lambda: ["read", "write", "shell", "network"],
    )

    # Paths
    workspace: Path = Path.cwd()
    data_dir: Path = Path.cwd() / ".bobanana"

    @classmethod
    def load(cls) -> "Settings":
        workspace = Path(_env("BOBANANA_WORKSPACE", str(Path.cwd()))).resolve()
        data_dir_raw = _env("BOBANANA_DATA_DIR", ".bobanana")
        data_dir = Path(data_dir_raw)
        if not data_dir.is_absolute():
            data_dir = workspace / data_dir

        default_skill_dirs = [
            Path.home() / ".agents" / "skills",
            Path.home() / ".cursor" / "skills",
            workspace / "skills",
        ]
        skill_dirs_env = _env("BOBANANA_SKILL_DIRS")
        if skill_dirs_env:
            skill_dirs = [Path(p.strip()).expanduser() for p in skill_dirs_env.split(os.pathsep) if p.strip()]
        else:
            skill_dirs = default_skill_dirs

        mcp_config_raw = _env("BOBANANA_MCP_CONFIG")
        mcp_config = Path(mcp_config_raw).expanduser() if mcp_config_raw else workspace / "mcp.json"

        inst = cls(
            api_key=_env("OPENAI_API_KEY"),
            base_url=_normalize_base_url(_env("OPENAI_BASE_URL")),
            model=_env("BOBANANA_MODEL", "gpt-4o-mini"),
            temperature=_env_float("BOBANANA_TEMPERATURE", 0.1),
            max_plan_revisions=_env_int("BOBANANA_MAX_PLAN_REVISIONS", 3),
            max_exec_revisions=_env_int("BOBANANA_MAX_EXEC_REVISIONS", 3),
            max_steps=_env_int("BOBANANA_MAX_STEPS", 20),
            max_tool_iters=_env_int("BOBANANA_MAX_TOOL_ITERS", 24),
            max_directive_revisions=_env_int("BOBANANA_MAX_DIRECTIVE_REVISIONS", 3),
            shell_timeout=_env_int("BOBANANA_SHELL_TIMEOUT", 120),
            task_timeout=_env_float("BOBANANA_TASK_TIMEOUT", 0.0),
            llm_timeout=_env_int("BOBANANA_LLM_TIMEOUT", 90),
            enable_checkpoints=_env_bool("BOBANANA_ENABLE_CHECKPOINTS", True),
            enable_intent=_env_bool("BOBANANA_ENABLE_INTENT", True),
            enable_exploration_cache=_env_bool("BOBANANA_ENABLE_EXPLORATION_CACHE", True),
            log_level=_env("BOBANANA_LOG_LEVEL", "INFO"),
            structured_output_method=_env("BOBANANA_STRUCTURED_OUTPUT", "auto"),
            enable_web_tools=_env_bool("BOBANANA_ENABLE_WEB_TOOLS", True),
            enable_metaprompt=_env_bool("BOBANANA_ENABLE_METAPROMPT", True),
            enable_delivery_gate=_env_bool("BOBANANA_ENABLE_DELIVERY_GATE", True),
            delivery_gate_skill=_env("BOBANANA_DELIVERY_GATE_SKILL", "code-delivery-gate"),
            enable_tool_plugins=_env_bool("BOBANANA_ENABLE_TOOL_PLUGINS", True),
            tool_permission_names=[
                p.strip() for p in (_env("BOBANANA_TOOL_PERMISSIONS", "read,write,shell,network") or "").split(",")
                if p.strip()
            ],
            skill_dirs=skill_dirs,
            mcp_config=mcp_config,
            agent_reach_repo=_env("BOBANANA_AGENT_REACH_REPO",
                                  "https://github.com/Panniantong/Agent-Reach.git"),
            workspace=workspace,
            data_dir=data_dir.resolve(),
        )
        return inst

    # Floors used when scaling the budget down for small tasks. The configured
    # values above act as the ceiling (t=1); these are the floor (t=0).
    _BUDGET_FLOORS = {
        "max_steps": 2,
        "max_tool_iters": 4,
        "max_exec_revisions": 1,
        "max_plan_revisions": 1,
        "max_directive_revisions": 1,
        "shell_timeout": 20,
    }

    def scaled_budget(self, task_size: float) -> dict:
        """Scale loop/tool budgets by task_size in [0,1].

        effective = round(floor + (ceiling - floor) * t), clamped to [floor, ceiling].
        Greeting-sized tasks get the cheap floor; large refactors get the full
        configured ceiling. Env-configured values remain the hard ceiling.
        """
        t = max(0.0, min(1.0, float(task_size)))
        out: dict[str, int] = {}
        for name, floor in self._BUDGET_FLOORS.items():
            ceiling = int(getattr(self, name))
            floor = min(floor, ceiling)
            out[name] = max(floor, min(ceiling, round(floor + (ceiling - floor) * t)))
        return out

    @property
    def has_llm(self) -> bool:
        return bool(self.api_key)

    @property
    def external_dir(self) -> Path:
        return self.data_dir / "external"

    @property
    def plugin_dir(self) -> Path:
        return self.data_dir / "tools"

    def permission_policy(self):
        from .tools.permissions import PermissionPolicy, parse_permissions
        return PermissionPolicy(parse_permissions(self.tool_permission_names))

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.external_dir.mkdir(parents=True, exist_ok=True)
        from .tools.registry import seed_plugin_directory
        seed_plugin_directory(self.plugin_dir)

    class Config:
        arbitrary_types_allowed = True
