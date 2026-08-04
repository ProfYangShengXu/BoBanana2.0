#!/usr/bin/env python3
"""BoBanana uninstaller — remove shortcut, venv, and optional local data."""

from __future__ import annotations

import argparse
import platform

from install_lib import (
    ROOT,
    VENV_DIR,
    default_data_dir,
    info,
    ok,
    remove_path,
    warn,
    windows_shortcut,
)


def _confirm(prompt: str) -> bool:
    try:
        ans = input(f"  {prompt} [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return ans in ("y", "yes")


def main() -> int:
    parser = argparse.ArgumentParser(description="BoBanana uninstaller")
    parser.add_argument(
        "--venv",
        action="store_true",
        help="Also remove .venv (Python virtual environment)",
    )
    parser.add_argument(
        "--data",
        action="store_true",
        help="Also remove BOBANANA_DATA_DIR (sessions, memory, etc.)",
    )
    parser.add_argument(
        "--env",
        action="store_true",
        help="Also remove .env (API keys)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Remove shortcut + .venv + data + .env (full local uninstall)",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompts",
    )
    parser.add_argument(
        "--shortcut-only",
        action="store_true",
        help="Only remove desktop shortcut (default when no flags)",
    )
    args = parser.parse_args()

    if args.all:
        args.venv = True
        args.data = True
        args.env = True

    do_venv = args.venv
    do_data = args.data
    do_env = args.env
    if not (do_venv or do_data or do_env or args.shortcut_only):
        args.shortcut_only = True

    print()
    print("  BoBanana — 卸载程序")
    print(f"  目录: {ROOT}")
    print(f"  系统: {platform.system()} {platform.release()}")
    print()

    if not args.yes and (do_venv or do_data or do_env):
        print("  将执行：")
        print("    - 删除桌面快捷方式")
        if do_venv:
            print("    - 删除 .venv")
        if do_data:
            print(f"    - 删除数据目录 {default_data_dir()}")
        if do_env:
            print("    - 删除 .env")
        print()
        if not _confirm("确认继续"):
            info("已取消")
            return 0

    if platform.system() == "Windows":
        try:
            windows_shortcut(remove=True)
            ok("桌面快捷方式已移除")
        except Exception as exc:
            warn(f"快捷方式移除失败: {exc}")
    else:
        info("非 Windows，跳过桌面快捷方式")

    if do_venv:
        remove_path(VENV_DIR, ".venv")

    if do_data:
        remove_path(default_data_dir(), "数据目录")

    if do_env:
        remove_path(ROOT / ".env", ".env")

    print()
    if do_venv or do_data or do_env:
        ok("卸载完成 — 可删除整个 BoBanana 文件夹")
    else:
        ok("快捷方式已移除 — 程序文件与 .env 保留")
    print("  重装: install.cmd 或 python install.py")
    print("  升级: 解压新版到同目录后再次运行 install.cmd")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
