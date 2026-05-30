"""Tests for bobanana.env_setup."""

from __future__ import annotations

import tempfile
from pathlib import Path

from bobanana.env_setup import (
    ensure_env_file,
    get_env_value,
    mask_secret,
    set_env_value,
)


def test_mask_secret():
    assert mask_secret("") == "(未设置)"
    assert mask_secret("abcd") == "****"
    assert mask_secret("sk-1234567890abcdef").startswith("sk-1")


def test_set_and_get_env_value(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=old\nBOBANANA_MODEL=gpt-4o-mini\n", encoding="utf-8")
    set_env_value("OPENAI_API_KEY", "sk-new", env)
    assert get_env_value("OPENAI_API_KEY", env) == "sk-new"
    set_env_value("OPENAI_BASE_URL", "https://api.deepseek.com/v1", env)
    assert get_env_value("OPENAI_BASE_URL", env) == "https://api.deepseek.com/v1"


def test_ensure_env_file_from_example(tmp_path: Path, monkeypatch):
    example = tmp_path / ".env.example"
    example.write_text("OPENAI_API_KEY=\nBOBANANA_MODEL=gpt-4o-mini\n", encoding="utf-8")
    target = tmp_path / ".env"
    monkeypatch.setattr("bobanana.env_setup.ENV_EXAMPLE", example)
    monkeypatch.setattr("bobanana.env_setup.ENV_FILE", target)
    ensure_env_file()
    assert target.is_file()
    assert "OPENAI_API_KEY" in target.read_text(encoding="utf-8")


def test_configure_api_non_interactive_skip(tmp_path: Path, monkeypatch, capsys):
    example = tmp_path / ".env.example"
    example.write_text("OPENAI_API_KEY=\n", encoding="utf-8")
    env = tmp_path / ".env"
    monkeypatch.setattr("bobanana.env_setup.ENV_EXAMPLE", example)
    monkeypatch.setattr("bobanana.env_setup.ENV_FILE", env)

    from bobanana.env_setup import configure_api

    ok = configure_api(skip_key=True, non_interactive=True, path=env)
    assert ok is False
    out = capsys.readouterr().out
    assert "skipped" in out.lower() or "跳过" in out
