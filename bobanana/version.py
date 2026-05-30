"""Single source of truth for BoBanana release versioning.

Bump ``__version__`` on each user-visible release; set ``RELEASE_TAG`` to a short
kebab-case label for logs and delivery notes (e.g. ``path-guard``).
"""

from __future__ import annotations

__version__ = "2.1.5"
RELEASE_TAG = "portable-install"  # cross-platform install, API configure wizard (2026-05-30)
RELEASE_DATE = "2026-05-30"


def version_line() -> str:
    """One-line string for CLI, selfcheck, and run logs."""
    return f"BoBanana {__version__} ({RELEASE_TAG}, {RELEASE_DATE})"


def version_short() -> str:
    """Compact label for banners."""
    return __version__
