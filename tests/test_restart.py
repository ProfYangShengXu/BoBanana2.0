"""Tests for cross-platform restart."""

from __future__ import annotations

import pytest


def test_restart_windows_execv(monkeypatch):
    import bobanana.restart as r

    calls: list[tuple] = []

    def fake_execv(exe, args):
        calls.append((exe, args))
        raise SystemExit(0)

    monkeypatch.setattr(r.os, "execv", fake_execv)
    monkeypatch.setattr(r.sys, "platform", "win32")

    with pytest.raises(SystemExit):
        r.restart(["prog", "-m", "bobanana", "--debug"])

    assert calls
    exe, args = calls[0]
    assert exe == args[0]
    assert args[1:] == ["-m", "bobanana", "--debug"]


def test_build_restart_argv_argv0_is_dash_m():
    from bobanana.restart import build_restart_argv

    argv = build_restart_argv(["-m", "bobanana", "--debug"])
    assert argv[1:] == ["-m", "bobanana", "--debug"]


def test_build_restart_argv_strips_stray_bobanana():
    from bobanana.restart import build_restart_argv

    argv = build_restart_argv(["prog", "bobanana", "--debug"])
    assert argv[1:] == ["-m", "bobanana", "--debug"]
