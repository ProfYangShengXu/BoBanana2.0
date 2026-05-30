"""Workspace folder selection (optional code workspace).

Opens a native directory picker when a GUI is available; degrades gracefully to
an instruction to pass the path manually when it is not (headless/SSH).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .logging_setup import get_logger

log = get_logger("workspace")


def pick_directory(title: str = "Select code workspace") -> Optional[Path]:
    """Open a native folder picker. Returns the chosen path, or None if cancelled/unavailable."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:  # tkinter missing (headless build)
        log.warning("file picker unavailable: %s", exc)
        return None

    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askdirectory(title=title)
        root.destroy()
    except Exception as exc:  # no display / Tcl error
        log.warning("file picker failed to open: %s", exc)
        return None

    if not chosen:
        return None
    return Path(chosen).resolve()


def validate_directory(path_str: str) -> tuple[Optional[Path], str]:
    """Validate a user-supplied path. Returns (resolved_path or None, message)."""
    if not path_str.strip():
        return None, "empty path"
    path = Path(path_str.strip()).expanduser()
    if not path.exists():
        return None, f"path does not exist: {path}"
    if not path.is_dir():
        return None, f"not a directory: {path}"
    return path.resolve(), "ok"
