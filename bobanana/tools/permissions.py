"""Fine-grained tool permission model.

Each tool declares required permissions; the runtime policy (from config) grants
a subset. Invocation is blocked when required ⊄ granted.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable, Set


class Permission(str, Enum):
    READ = "read"          # read/list files, pure information
    WRITE = "write"        # create/overwrite workspace files
    SHELL = "shell"        # run allowlisted shell commands
    NETWORK = "network"    # HTTP / git clone / web search
    ADMIN = "admin"        # elevated ops (load repos, plugin management)


# Default grant: everything except ADMIN.
DEFAULT_GRANTED: frozenset[Permission] = frozenset({
    Permission.READ, Permission.WRITE, Permission.SHELL, Permission.NETWORK,
})

ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)


def parse_permissions(raw: Iterable[str] | None) -> Set[Permission]:
    if not raw:
        return set()
    out: Set[Permission] = set()
    for item in raw:
        key = str(item).strip().lower()
        if not key:
            continue
        try:
            out.add(Permission(key))
        except ValueError as exc:
            raise ValueError(f"unknown permission: {item!r}") from exc
    return out


def format_permissions(perms: Iterable[Permission]) -> str:
    return ",".join(sorted(p.value for p in perms))


class PermissionPolicy:
    def __init__(self, granted: Iterable[Permission] | None = None) -> None:
        self.granted: Set[Permission] = set(granted if granted is not None else DEFAULT_GRANTED)

    def allows(self, required: Iterable[Permission]) -> bool:
        req = set(required)
        return req.issubset(self.granted)

    def missing(self, required: Iterable[Permission]) -> Set[Permission]:
        return set(required) - self.granted

    def deny_message(self, tool_name: str, required: Iterable[Permission]) -> str:
        missing = self.missing(required)
        return (
            f"ERROR: permission denied for `{tool_name}` — requires "
            f"[{format_permissions(required)}], missing [{format_permissions(missing)}]. "
            f"Granted: [{format_permissions(self.granted)}]."
        )
