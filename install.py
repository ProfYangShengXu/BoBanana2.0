#!/usr/bin/env python3
"""Cross-platform BoBanana installer.

Works on Windows, macOS, and Linux. Prefer running via:
  - Windows: double-click install.cmd
  - macOS/Linux: ./install.sh
  - Any OS: python install.py
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"


def _venv_python() -> Path:
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _info(msg: str) -> None:
    print(f"[install] {msg}")


def _ok(msg: str) -> None:
    print(f"[install] OK: {msg}")


def _fail(msg: str) -> None:
    print(f"[install] FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def find_python() -> str:
    if sys.version_info >= (3, 10):
        ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        _ok(f"Python {ver} ({sys.executable})")
        return sys.executable
    for cmd in ("python3", "python"):
        exe = shutil.which(cmd)
        if not exe or exe == sys.executable:
            continue
        try:
            out = subprocess.check_output(
                [
                    exe,
                    "-c",
                    "import sys; print('.'.join(map(str, (sys.version_info.major, sys.version_info.minor))))",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            major, minor = map(int, out.split("."))
            if major > 3 or (major == 3 and minor >= 10):
                _ok(f"Python {out} ({exe})")
                return exe
        except (subprocess.CalledProcessError, ValueError):
            continue
    _fail(
        "找不到 Python 3.10 或更高版本。\n"
        "  Windows: https://www.python.org/downloads/ （勾选 Add Python to PATH）\n"
        "  macOS:   brew install python@3.12\n"
        "  Linux:   sudo apt install python3 python3-venv python3-pip"
    )


def ensure_venv(py: str) -> Path:
    vpy = _venv_python()
    if not vpy.is_file():
        _info("正在创建虚拟环境 .venv …")
        subprocess.check_call([py, "-m", "venv", str(VENV_DIR)])
    _info("正在安装 / 更新依赖 …")
    subprocess.check_call([str(vpy), "-m", "pip", "install", "--upgrade", "pip", "-q"])
    req = ROOT / "requirements.txt"
    subprocess.check_call([str(vpy), "-m", "pip", "install", "-r", str(req)])
    _ok("依赖已就绪")
    return vpy


def run_selfcheck(vpy: Path) -> None:
    _info("运行离线自检 …")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    subprocess.check_call([str(vpy), "-m", "bobanana", "--selfcheck"], env=env, cwd=str(ROOT))
    _ok("自检通过")


def windows_shortcut() -> None:
    ps1 = ROOT / "create-desktop-shortcut.ps1"
    if not ps1.is_file():
        _info("跳过桌面快捷方式（create-desktop-shortcut.ps1 不存在）")
        return
    subprocess.check_call(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
        cwd=str(ROOT),
    )


def unix_hint() -> None:
    bb = ROOT / "bb.sh"
    print()
    print("  macOS / Linux 启动方式：")
    print(f"    cd \"{ROOT}\"")
    print("    chmod +x bb.sh install.sh   # 只需第一次")
    print("    ./bb.sh start               # 跑测试后启动")
    print("    ./bb.sh use                 # 快速启动（跳过测试）")
    print("    ./bb.sh config              # 重新配置 API")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="BoBanana portable installer")
    parser.add_argument("--api-key", default="", help="OPENAI_API_KEY (non-interactive)")
    parser.add_argument("--base-url", default="", help="OPENAI_BASE_URL")
    parser.add_argument("--model", default="", help="BOBANANA_MODEL")
    parser.add_argument("--skip-api-key", action="store_true", help="Skip API key prompt")
    parser.add_argument("--skip-tests", action="store_true", help="Skip selfcheck")
    parser.add_argument("--no-shortcut", action="store_true", help="Skip desktop shortcut (Windows)")
    parser.add_argument("--uninstall", action="store_true", help="Remove desktop shortcut only (Windows)")
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))
    from bobanana.env_setup import configure_api, print_env_summary

    print()
    print("  BoBanana 2.0 — 跨平台安装程序")
    print(f"  系统: {platform.system()} {platform.release()}")
    print(f"  目录: {ROOT}")
    print()

    if args.uninstall:
        if platform.system() == "Windows":
            ps1 = ROOT / "create-desktop-shortcut.ps1"
            if ps1.is_file():
                subprocess.call(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1), "-Remove"],
                    cwd=str(ROOT),
                )
        _ok("卸载完成（仅移除快捷方式；文件夹与 .env 保留）")
        return 0

    py = find_python()
    vpy = ensure_venv(py)

    non_interactive = bool(args.api_key or args.skip_api_key)
    configure_api(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        skip_key=args.skip_api_key,
        non_interactive=non_interactive,
    )
    print_env_summary()

    if not args.skip_tests:
        run_selfcheck(vpy)

    if platform.system() == "Windows" and not args.no_shortcut:
        windows_shortcut()
    elif platform.system() != "Windows":
        unix_hint()

    print()
    _ok("安装完成")
    if platform.system() == "Windows":
        print("  下一步: 双击桌面「BoBanana 2.0」，或运行 .\\bb.cmd use")
    print("  改 API: bb config  或  python -m bobanana --configure")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
