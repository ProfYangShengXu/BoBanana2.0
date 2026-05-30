"""Real-LLM end-to-end acceptance tests.

These exercise the FULL pipeline (intent → plan → execute → review → directive
gate → finalize) against the live model configured via OPENAI_API_KEY. They are
skipped automatically when no key is present, so the offline suite stays green
and CI without secrets doesn't fail.

Run explicitly:
    set BOBANANA_TASK_TIMEOUT=300   # optional safety net
    pytest -q -m live tests/test_e2e_live.py
or just `pytest tests/test_e2e_live.py` (auto-skips without a key).

Kept intentionally small/cheap: one tiny file-creation task plus an intent check.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

_NO_KEY = not os.getenv("OPENAI_API_KEY")
_SKIP_REASON = "no OPENAI_API_KEY configured — skipping live LLM e2e"


@pytest.mark.skipif(_NO_KEY, reason=_SKIP_REASON)
def test_live_intent_sizes_greeting_vs_refactor(tmp_path):
    from bobanana.config import Settings
    from bobanana.app import Application

    settings = Settings.load()
    settings.workspace = tmp_path
    settings.data_dir = tmp_path / ".bobanana"
    settings.ensure_dirs()
    app = Application(settings)
    try:
        greeting = app.classify_intent("你好")
        big = app.classify_intent("把整个项目按领域拆分成多个模块并补齐单元测试与文档")
        # Greetings should be tiny; large refactors should clearly outrank them.
        assert greeting.task_size < 0.3
        assert big.task_size > greeting.task_size
        assert big.is_code_task is True
    finally:
        app.close()


@pytest.mark.skipif(_NO_KEY, reason=_SKIP_REASON)
def test_live_creates_a_file_end_to_end(tmp_path):
    from bobanana.config import Settings
    from bobanana.app import Application

    settings = Settings.load()
    settings.workspace = tmp_path
    settings.data_dir = tmp_path / ".bobanana"
    # Bound the run so a flaky model can't hang the suite.
    if not settings.task_timeout:
        settings.task_timeout = 300.0
    settings.ensure_dirs()

    app = Application(settings)
    events: list[dict] = []
    try:
        request = ("在工作区创建文件 hello.txt，内容恰好为一行：Hello, BoBanana! "
                   "不要创建其它文件。")
        result = app.run_task(request, on_event=events.append, difficulty=0.2)

        assert result.get("done") is True, f"run did not finish: {result.get('status')}"
        # The acceptance criterion: the file exists with the expected content.
        target = tmp_path / "hello.txt"
        assert target.exists(), "agent did not create hello.txt"
        assert "Hello, BoBanana!" in target.read_text(encoding="utf-8")
        # And the pipeline emitted a final result.
        assert any(e.get("kind") == "final" for e in events)
    finally:
        app.close()
