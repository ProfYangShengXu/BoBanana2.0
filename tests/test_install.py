"""Tests for install_lib (merge env, version detection)."""

from __future__ import annotations

import shutil
from pathlib import Path

import install_lib


def test_merge_env_from_example_adds_missing_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(install_lib, "ROOT", tmp_path)
    (tmp_path / ".env.example").write_text(
        "OPENAI_API_KEY=\nBOBANANA_NEW_FLAG=1\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")
    added = install_lib.merge_env_from_example()
    assert added == 1
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "BOBANANA_NEW_FLAG=1" in text
    assert "sk-test" in text


def test_merge_env_creates_from_example(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(install_lib, "ROOT", tmp_path)
    (tmp_path / ".env.example").write_text("FOO=bar\n", encoding="utf-8")
    added = install_lib.merge_env_from_example()
    assert added >= 1
    assert (tmp_path / ".env").is_file()


def test_ensure_ripgrep_skip_when_rg_on_path() -> None:
    if not shutil.which("rg"):
        import pytest

        pytest.skip("rg not installed")
    assert install_lib.ensure_ripgrep(skip=True) is True
