"""Re-exec the current process so code/config changes take effect."""

from __future__ import annotations

import os
import sys


def build_restart_argv(argv: list[str] | None = None) -> list[str]:
    """Build argv for ``os.execv`` that preserves CLI flags (e.g. ``--debug``)."""
    raw = list(argv if argv is not None else sys.argv)
    flags = raw[1:]
    return [sys.executable, "-m", "bobanana", *flags]


def restart(argv: list[str] | None = None) -> None:
    """Replace this process with a fresh BoBanana run. Does not return on success."""
    os.execv(sys.executable, build_restart_argv(argv))
