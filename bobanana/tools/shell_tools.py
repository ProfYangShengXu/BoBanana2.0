"""Controlled shell execution.

Lightweight protection: a command-prefix allowlist, a hard timeout, output
truncation, and execution pinned to the workspace directory.
"""

from __future__ import annotations

import platform
import re
import shlex
import subprocess
from pathlib import Path

from ..logging_setup import get_logger

log = get_logger("shell")

IS_WINDOWS = platform.system() == "Windows"

# Cross-platform tooling: behaves the same on Windows and POSIX.
COMMON_COMMANDS = {
    "python", "python3", "pip", "pytest", "ruff", "flake8", "mypy",
    "node", "npm", "npx", "pnpm", "yarn", "go", "cargo", "git", "rg", "echo", "tree",
    # Agent-Reach / web reach CLIs (used after loading the agent-reach skill)
    "agent-reach", "mcporter", "curl", "gh", "yt-dlp", "rdt", "twitter", "xhs",
}
# Windows shell builtins / executables.
WINDOWS_COMMANDS = {"dir", "type", "where", "findstr", "copy", "more", "cd"}
# POSIX shell utilities.
POSIX_COMMANDS = {"ls", "cat", "grep", "find", "which", "head", "tail", "sort",
                  "wc", "cp", "mv", "pwd"}


def default_allowlist() -> set[str]:
    """Build the command allowlist for the host OS (auto-detected)."""
    os_specific = WINDOWS_COMMANDS if IS_WINDOWS else POSIX_COMMANDS
    return COMMON_COMMANDS | os_specific


# Resolved once for the running OS; ShellRunner uses this unless overridden.
DEFAULT_ALLOWLIST = default_allowlist()

# Unix-only commands that simply don't exist on a stock Windows shell.
_POSIX_ONLY_CMDS = re.compile(
    r"(?:^|[\s|&;(])(ldconfig|ldd|uname|apt|apt-get|aptitude|yum|dnf|pacman|brew|"
    r"dpkg|systemctl|service|sudo|man|which)\b"
)
# Absolute Unix filesystem paths used as command targets.
_POSIX_PATHS = re.compile(r"(?:^|[\s=\"'])/(usr|etc|var|proc|opt|bin|lib|lib64|home|root|sys|dev)(?:/|\b)")


def shell_environment_hint(allowlist: set[str] | None = None) -> str:
    """Describe the host shell + confirmed command library for the executor prompt."""
    allowed = ", ".join(sorted(allowlist if allowlist is not None else DEFAULT_ALLOWLIST))
    if IS_WINDOWS:
        base = (
            "OS=Windows, shell=cmd.exe. Use Windows syntax: `where` not `which`, "
            "`dir`/`type` not `ls -l`/`cat` flags, `2>nul` not `2>/dev/null`, and Windows "
            "paths (no /usr, /etc). Prefer cross-platform `python`, `git`, `pytest`. "
            "To inspect files or directories, prefer the read_file/list_dir tools over shell."
        )
    else:
        base = f"OS={platform.system()}, shell=/bin/sh. Standard POSIX syntax is fine."
    return f"{base} Allowed first-token commands: {allowed}."


def is_shell_reading_file(command: str, target_path: str) -> bool:
    """True when shell command reads file contents (type/cat/findstr/...)."""
    command = command.strip()
    if not command or not target_path:
        return False
    target = normalize_path_for_shell(target_path)
    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:
        tokens = command.split()
    if not tokens:
        return False
    first = tokens[0].strip('"').lower()
    readers = {"type", "cat", "head", "tail", "more", "findstr"}
    if first not in readers:
        return False
    cmd_norm = normalize_path_for_shell(command)
    return target in cmd_norm or target.replace("/", "\\") in cmd_norm


def normalize_path_for_shell(path: str) -> str:
    return path.replace("\\", "/").strip().strip('"').lstrip("./")


def is_directory_exploration_command(command: str) -> bool:
    """True when the command only lists directories (use list_dir instead)."""
    command = command.strip()
    if not command:
        return False
    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:
        tokens = command.split()
    if not tokens:
        return False
    first = tokens[0].strip('"').lower()
    if first == "dir":
        return True
    if first == "ls" and len(tokens) <= 3:
        # ls, ls ., ls -la path — exploration, not build/test
        flag_tokens = [t for t in tokens[1:] if t.startswith("-")]
        path_tokens = [t for t in tokens[1:] if not t.startswith("-")]
        allowed_flags = {"-l", "-a", "-la", "-al", "-lah"}
        if flag_tokens and all(t in allowed_flags for t in flag_tokens):
            return True
        if not flag_tokens and len(path_tokens) <= 1:
            return True
    if first in ("find", "tree") and len(tokens) <= 4:
        return True
    return False


def looks_posix_only(command: str) -> str | None:
    """Return a corrective hint if a command uses Unix-only syntax (Windows only)."""
    if "/dev/null" in command:
        return "it redirects to /dev/null (Unix); on Windows use `2>nul` or omit the redirect"
    m = _POSIX_ONLY_CMDS.search(command)
    if m:
        return f"it uses the Unix-only command `{m.group(1)}`, which is unavailable on Windows"
    if _POSIX_PATHS.search(command):
        return "it references a Unix filesystem path (e.g. /usr, /etc) that does not exist on Windows"
    return None


class ShellRunner:
    def __init__(self, workspace: Path, timeout: int = 60, allowlist: set[str] | None = None) -> None:
        self.workspace = workspace.resolve()
        self.timeout = timeout
        self.allowlist = allowlist if allowlist is not None else DEFAULT_ALLOWLIST
        log.info("shell command library confirmed for OS=%s: %d commands",
                 platform.system(), len(self.allowlist))

    def run(self, command: str, max_chars: int = 8000) -> str:
        command = command.strip()
        if not command:
            return "ERROR: empty command"
        try:
            first = shlex.split(command, posix=False)[0]
        except ValueError:
            first = command.split()[0]
        first = first.strip('"').lower()
        if first not in self.allowlist:
            return (
                f"ERROR: command '{first}' is not in the allowlist. "
                f"Allowed: {', '.join(sorted(self.allowlist))}"
            )
        if is_directory_exploration_command(command):
            return (
                "ERROR: use list_dir or read_file to explore the workspace — "
                "do not use run_shell for directory listing (dir/ls/find). "
                "This is not a timeout; revise your tool choice."
            )
        if IS_WINDOWS:
            hint = looks_posix_only(command)
            if hint:
                return (
                    f"ERROR: command not run — {hint}. You are on Windows (cmd.exe). "
                    "Rewrite it with Windows syntax, or use the read_file/list_dir/python "
                    "tools instead of Unix shell utilities."
                )
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            # Distinct TIMEOUT marker: the executor turns this into a replan signal
            # rather than blindly retrying the same long-running command.
            return (
                f"ERROR: TIMEOUT after {self.timeout}s running `{command[:120]}`. "
                "The current approach is stuck — do NOT re-run this; a different "
                "command or a revised plan is needed."
            )
        except Exception as exc:  # surface execution errors to the agent
            return f"ERROR: failed to run command: {exc}"

        out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        if len(out) > max_chars:
            out = out[:max_chars] + f"\n... [truncated {len(out) - max_chars} chars]"
        result = f"[exit={proc.returncode}]\n{out}".strip()
        if proc.returncode != 0 and IS_WINDOWS and not (proc.stdout or proc.stderr):
            result += ("\n[hint] non-zero exit with no output often means a Unix-only "
                       "command/path on Windows — verify the command exists on Windows.")
        return result
