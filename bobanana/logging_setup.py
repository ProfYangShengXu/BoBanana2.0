"""Centralized logging so users can watch the agent's run in the terminal.

Uses rich's handler for readable, colorized output. Call :func:`setup_logging`
once at startup; everywhere else use ``get_logger(__name__)``.
"""

from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler

_LOGGER_NAME = "bobanana"
_configured = False


def setup_logging(level: str = "INFO", console: Console | None = None) -> logging.Logger:
    """Configure the 'bobanana' logger. Safe to call multiple times."""
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    numeric = getattr(logging, str(level).upper(), logging.INFO)
    logger.setLevel(numeric)

    if not _configured:
        handler = RichHandler(
            console=console or Console(stderr=True),
            show_time=True,
            show_path=False,
            rich_tracebacks=True,
            markup=False,
        )
        handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%H:%M:%S]"))
        logger.addHandler(handler)
        logger.propagate = False
        _configured = True
    else:
        for h in logger.handlers:
            h.setLevel(numeric)
    return logger


def set_level(level: str) -> None:
    logging.getLogger(_LOGGER_NAME).setLevel(getattr(logging, str(level).upper(), logging.INFO))


def get_logger(name: str | None = None) -> logging.Logger:
    if name:
        return logging.getLogger(f"{_LOGGER_NAME}.{name}")
    return logging.getLogger(_LOGGER_NAME)
