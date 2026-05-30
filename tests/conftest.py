"""Pytest fixtures/config shared across the suite.

Loads the project .env early so OPENAI_API_KEY (and friends) are visible at
collection time — this is what flips the live e2e tests from skipped to active
when a key is configured.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env", override=False)
