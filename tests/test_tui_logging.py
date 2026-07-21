"""Tests for TUI log bridge (main-thread flush)."""

from __future__ import annotations

import logging
import threading

from bobanana.logging_setup import enable_tui_log_bridge, flush_tui_logs, get_logger, setup_logging


def test_tui_log_bridge_flushes_on_main_thread():
    setup_logging()
    enable_tui_log_bridge()
    log = get_logger("app")
    errors: list[str] = []

    def worker() -> None:
        try:
            log.info("worker log line")
        except Exception as exc:
            errors.append(str(exc))

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    n = flush_tui_logs()
    assert not errors
    assert n >= 1
