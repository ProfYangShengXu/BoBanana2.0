"""Session-scoped blocklist for permanently failing tool attempts.

When a path or shell command class has already failed with an error that will
not succeed on retry (outside workspace, file not found, allowlist denial, etc.),
subsequent identical attempts are short-circuited without invoking the tool —
saving LLM rounds and tokens (see 5.31-4 post-mortem).
"""

from __future__ import annotations

import re
from typing import Any

from .logging_setup import get_logger
from .memory.structured_memory import _norm_cache_path

log = get_logger("blocklist")

_SCRATCH_PATHS = "_blocked_tool_paths"
_SCRATCH_SHELL = "_blocked_shell_stems"

# Tool results that indicate retrying the same target is pointless this task.
_PERMANENT_MARKERS = (
    "outside workspace",
    "Refusing to access",
    "file not found:",
    "not a file:",
    "not in the allowlist",
    "command not run —",
    "do not use run_shell for directory listing",
    "do not read prior delivery output",
    "do not read_file the deliverable",
    "old_string not found",
    "permission denied for `",
)


def _blocked_paths(scratch: dict[str, Any]) -> dict[str, str]:
    return scratch.setdefault(_SCRATCH_PATHS, {})


def _blocked_shell(scratch: dict[str, Any]) -> dict[str, str]:
    return scratch.setdefault(_SCRATCH_SHELL, {})


def normalize_block_path(path: str) -> str:
    return _norm_cache_path(path)


def shell_failure_stem(command: str) -> str:
    """Cluster near-identical shell spins (e.g. truncated `cd ... && py`)."""
    c = " ".join((command or "").strip().split())
    if not c:
        return "shell:<empty>"
    if " && " in c.lower():
        parts = re.split(r"\s+&&\s+", c, maxsplit=1, flags=re.I)
        if len(parts) == 2:
            head, tail = parts[0].strip(), parts[1].strip()
            # Truncated or meaningless tails: py, fi, di, fo, de, ty, if, ...
            if len(tail) <= 5 and tail.isalpha():
                # Cluster py/fi/di/fo/de… spins from truncated commands (5.31-4).
                return f"shell:{head} && <short-tail>"
    return f"shell:{c[:160]}"


def _path_from_args(tool_name: str, args: dict) -> str | None:
    path = args.get("path")
    if isinstance(path, str) and path.strip():
        if tool_name in ("read_file", "write_file", "edit_file", "list_dir"):
            return normalize_block_path(path)
    return None


def _path_block_key(tool_name: str, norm: str) -> str:
    """Read failures must not block write_file on the same path (6.1 deliverable)."""
    if tool_name == "read_file":
        return f"read:{norm}"
    if tool_name in ("write_file", "edit_file"):
        return f"write:{norm}"
    if tool_name == "list_dir":
        return f"list:{norm}"
    return norm


def is_permanent_failure(result: str) -> bool:
    r = (result or "").lstrip()
    if not r.startswith("ERROR"):
        return False
    low = r.lower()
    return any(m.lower() in low for m in _PERMANENT_MARKERS)


def record_tool_failure(scratch: dict[str, Any], tool_name: str, args: dict, result: str) -> None:
    if not is_permanent_failure(result):
        return
    snippet = str(result).strip().splitlines()[0][:200]
    norm = _path_from_args(tool_name, args)
    if norm is not None:
        key = _path_block_key(tool_name, norm)
        _blocked_paths(scratch)[key] = snippet
        log_key = key
    elif tool_name == "run_shell":
        cmd = str(args.get("command", ""))
        stem = shell_failure_stem(cmd)
        _blocked_shell(scratch)[stem] = snippet
        log_key = stem
    else:
        return
    log.info("blocked permanent failure: %s — %s", log_key, snippet[:80])


def check_tool_blocked(scratch: dict[str, Any] | None, tool_name: str, args: dict) -> str | None:
    """Return an ERROR string if this call must not run again this task."""
    if scratch is None:
        return None
    norm = _path_from_args(tool_name, args)
    if norm is not None:
        key = _path_block_key(tool_name, norm)
        prior = _blocked_paths(scratch).get(key)
        if prior:
            return (
                f"ERROR: blocked — path '{norm}' permanently failed this task; "
                "do not retry (use a workspace-relative path or another tool)."
            )
    if tool_name == "run_shell":
        cmd = str(args.get("command", ""))
        stem = shell_failure_stem(cmd)
        if _blocked_shell(scratch).get(stem):
            return (
                "ERROR: blocked — this shell command pattern permanently failed this task; "
                "change approach (read_file/list_dir or a different command)."
            )
    return None


def clear_blocklist(scratch: dict[str, Any]) -> None:
    """Clear blocklists (e.g. on workspace reset)."""
    scratch.pop(_SCRATCH_PATHS, None)
    scratch.pop(_SCRATCH_SHELL, None)
    scratch.pop("_reads_this_task", None)
    scratch.pop("_grep_recent", None)
    scratch.pop("allow_full_write", None)
