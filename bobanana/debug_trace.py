"""NDJSON debug traces for Cursor debug mode (session-scoped)."""

from __future__ import annotations

import json
import time
from pathlib import Path

_SESSION_ID = "b8f572"
_LOG_NAME = f"debug-{_SESSION_ID}.log"


def agent_debug_log(
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict | None = None,
    *,
    run_id: str = "pre-fix",
) -> None:
    # region agent log
    try:
        root = Path(__file__).resolve().parent.parent
        payload = {
            "sessionId": _SESSION_ID,
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with (root / _LOG_NAME).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass
    # endregion
