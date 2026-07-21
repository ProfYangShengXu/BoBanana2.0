"""Shared helpers for install.py / uninstall.py (stdlib only)."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"


def info(msg: str) -> None:
    print(f"[install] {msg}")


def ok(msg: str) -> None:
    print(f"[install] OK: {msg}")


def warn(msg: str) -> None:
    print(f"[install] WARN: {msg}")


def fail(msg: str) -> None:
    print(f"[install] FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def venv_python() -> Path:
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _refresh_windows_path() -> None:
    """Reload PATH from registry so a just-installed winget binary is visible."""
    if platform.system() != "Windows":
        return
    try:
        merged = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + "
                "[Environment]::GetEnvironmentVariable('Path','User')",
            ],
            text=True,
            timeout=30,
        ).strip()
        if merged:
            os.environ["PATH"] = merged
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _rg_version_line() -> str | None:
    exe = shutil.which("rg")
    if not exe:
        return None
    try:
        return subprocess.check_output([exe, "--version"], text=True, timeout=10).splitlines()[0]
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _install_ripgrep_windows() -> bool:
    if shutil.which("rg"):
        return True
    if not shutil.which("winget"):
        warn(
            "未找到 winget，无法自动安装 ripgrep。\n"
            "  请手动: winget install BurntSushi.ripgrep.MSVC\n"
            "  或从 https://github.com/BurntSushi/ripgrep/releases 下载"
        )
        return False
    info("正在通过 winget 安装 ripgrep …")
    proc = subprocess.run(
        [
            "winget",
            "install",
            "--id",
            "BurntSushi.ripgrep.MSVC",
            "-e",
            "--accept-source-agreements",
            "--accept-package-agreements",
        ],
        timeout=180,
    )
    _refresh_windows_path()
    if shutil.which("rg"):
        return True
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        link = Path(local) / "Microsoft" / "WinGet" / "Links" / "rg.exe"
        if link.is_file():
            os.environ["PATH"] = str(link.parent) + os.pathsep + os.environ.get("PATH", "")
            return True
    if proc.returncode == 0:
        warn("ripgrep 可能已安装；请新开终端后运行 rg --version 确认")
    return bool(shutil.which("rg"))


def _install_ripgrep_darwin() -> bool:
    if shutil.which("rg"):
        return True
    if not shutil.which("brew"):
        warn("未找到 Homebrew。请安装后执行: brew install ripgrep")
        return False
    info("正在通过 Homebrew 安装 ripgrep …")
    subprocess.run(["brew", "install", "ripgrep"], timeout=600)
    return bool(shutil.which("rg"))


def _install_ripgrep_linux() -> bool:
    if shutil.which("rg"):
        return True
    if shutil.which("apt-get"):
        warn("请安装 ripgrep: sudo apt-get update && sudo apt-get install -y ripgrep")
    elif shutil.which("dnf"):
        warn("请安装 ripgrep: sudo dnf install -y ripgrep")
    elif shutil.which("pacman"):
        warn("请安装 ripgrep: sudo pacman -S ripgrep")
    else:
        warn("请从发行版包管理器安装 ripgrep，或见 https://github.com/BurntSushi/ripgrep#installation")
    return False


def ensure_ripgrep(*, skip: bool = False) -> bool:
    """Ensure ``rg`` is on PATH for BoBanana ``grep_file`` (best-effort)."""
    if skip:
        info("跳过 ripgrep 自动安装（--skip-ripgrep）")
        line = _rg_version_line()
        if line:
            ok(line)
            return True
        warn("未检测到 rg；grep_file 在 Windows 上会回退 findstr")
        return False

    line = _rg_version_line()
    if line:
        ok(f"系统依赖 ripgrep: {line}")
        return True

    info("正在安装系统依赖 ripgrep (rg) — Agent 的 grep_file 工具需要 …")
    system = platform.system()
    if system == "Windows":
        installed = _install_ripgrep_windows()
    elif system == "Darwin":
        installed = _install_ripgrep_darwin()
    else:
        installed = _install_ripgrep_linux()

    line = _rg_version_line()
    if line:
        ok(f"ripgrep 就绪: {line}")
        return True
    if not installed:
        warn(
            "ripgrep 未就绪；grep_file 在 Windows 上会使用 findstr 回退（功能受限）。"
            "安装后请新开终端。"
        )
    return False


def find_python() -> str:
    if sys.version_info >= (3, 10):
        ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        ok(f"Python {ver} ({sys.executable})")
        return sys.executable
    for cmd in ("python3", "python", "py"):
        if cmd == "py":
            exe = shutil.which("py")
            if not exe:
                continue
            args = [exe, "-3"]
        else:
            exe = shutil.which(cmd)
            if not exe:
                continue
            args = [exe]
        try:
            out = subprocess.check_output(
                [
                    *args,
                    "-c",
                    "import sys; print('.'.join(map(str, (sys.version_info.major, sys.version_info.minor))))",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            major, minor = map(int, out.split("."))
            if major > 3 or (major == 3 and minor >= 10):
                ok(f"Python {out} ({' '.join(args)})")
                return " ".join(args) if cmd == "py" else exe
        except (subprocess.CalledProcessError, ValueError, FileNotFoundError):
            continue
    fail(
        "找不到 Python 3.10 或更高版本。\n"
        "  Windows: https://www.python.org/downloads/ （勾选 Add Python to PATH）\n"
        "  macOS:   brew install python@3.12\n"
        "  Linux:   sudo apt install python3 python3-venv python3-pip"
    )


def split_python_cmd(py: str) -> list[str]:
    return py.split() if " " in py else [py]


def read_package_version() -> str:
    vf = ROOT / "VERSION"
    if vf.is_file():
        return vf.read_text(encoding="utf-8").strip()
    return "unknown"


def read_installed_version(vpy: Path | None = None) -> str | None:
    vpy = vpy or venv_python()
    if not vpy.is_file():
        return None
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    try:
        out = subprocess.check_output(
            [str(vpy), "-c", "from bobanana.version import __version__; print(__version__)"],
            text=True,
            stderr=subprocess.DEVNULL,
            env=env,
            cwd=str(ROOT),
        ).strip()
        return out or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def existing_install() -> bool:
    return venv_python().is_file()


def merge_env_from_example() -> int:
    """Append missing keys from .env.example into .env. Returns count added."""
    example = ROOT / ".env.example"
    env_path = ROOT / ".env"
    if not example.is_file():
        return 0
    if not env_path.is_file():
        env_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        return len(example.read_text(encoding="utf-8").splitlines())

    existing_keys: set[str] = set()
    for line in env_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m:
            existing_keys.add(m.group(1))

    added = 0
    out_lines = env_path.read_text(encoding="utf-8").splitlines()
    for line in example.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if not m:
            continue
        key = m.group(1)
        if key not in existing_keys:
            if out_lines and out_lines[-1].strip():
                out_lines.append("")
            out_lines.append(line)
            existing_keys.add(key)
            added += 1
    if added:
        env_path.write_text("\n".join(out_lines).rstrip() + "\n", encoding="utf-8")
    return added


def windows_shortcut(*, remove: bool = False) -> None:
    if platform.system() != "Windows":
        return
    ps1 = ROOT / "create-desktop-shortcut.ps1"
    if not ps1.is_file():
        warn("create-desktop-shortcut.ps1 不存在，跳过快捷方式")
        return
    args = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ps1),
    ]
    if remove:
        args.append("-Remove")
    subprocess.check_call(args, cwd=str(ROOT))


def default_data_dir() -> Path:
    env = os.environ.get("BOBANANA_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".bobanana"


def remove_path(path: Path, label: str) -> None:
    if not path.exists():
        info(f"跳过 {label}（不存在）: {path}")
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    ok(f"已删除 {label}: {path}")
