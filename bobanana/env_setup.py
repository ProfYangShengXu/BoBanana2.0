"""Cross-platform .env setup for BoBanana (install wizard + bb config)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
ENV_FILE = PROJECT_ROOT / ".env"

# OpenAI-compatible presets (name, base_url or None, default_model, hint)
PROVIDER_PRESETS: tuple[tuple[str, str | None, str, str], ...] = (
    ("OpenAI", None, "gpt-4o-mini", "官方 OpenAI；Base URL 留空即可"),
    ("DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat", "需填 DeepSeek API Key"),
    ("Moonshot (Kimi)", "https://api.moonshot.cn/v1", "moonshot-v1-8k", "需填 Moonshot API Key"),
    ("Together AI", "https://api.together.xyz/v1", "meta-llama/Llama-3-8b-chat-hf", "Together 控制台获取 Key"),
    ("本地 OpenAI 兼容", "http://127.0.0.1:11434/v1", "llama3", "Ollama / vLLM 等本地服务地址"),
    ("自定义", "", "", "自己填 Base URL 和模型名"),
)


def mask_secret(value: str, visible: int = 4) -> str:
    if not value:
        return "(未设置)"
    if len(value) <= visible * 2:
        return "*" * len(value)
    return value[:visible] + "…" + value[-visible:]


def read_env_lines(path: Path | None = None) -> list[str]:
    path = path or ENV_FILE
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def write_env_lines(lines: list[str], path: Path | None = None) -> None:
    path = path or ENV_FILE
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def ensure_env_file() -> Path:
    if not ENV_EXAMPLE.is_file():
        raise FileNotFoundError(f".env.example not found at {ENV_EXAMPLE}")
    if not ENV_FILE.is_file():
        ENV_FILE.write_text(ENV_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    return ENV_FILE


def get_env_value(key: str, path: Path | None = None) -> str | None:
    path = path or ENV_FILE
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*)$")
    for line in read_env_lines(path):
        m = pattern.match(line)
        if m:
            val = m.group(1).strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            if val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            return val if val else None
    return None


def set_env_value(key: str, value: str, path: Path | None = None) -> None:
    path = path or ENV_FILE
    ensure_env_file()
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    lines = read_env_lines(path)
    replaced = False
    out: list[str] = []
    for line in lines:
        if pattern.match(line):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")
    write_env_lines(out, path)


def env_status(path: Path | None = None) -> dict[str, str | None]:
    path = path or ENV_FILE
    keys = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "BOBANANA_MODEL")
    return {k: get_env_value(k, path) for k in keys}


def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    try:
        if secret and sys.stdin.isatty():
            import getpass

            raw = getpass.getpass(f"  {label}{suffix}: ")
        else:
            raw = input(f"  {label}{suffix}: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    raw = raw.strip()
    return raw if raw else default


def _choose_provider() -> tuple[str | None, str, str]:
    print()
    print("  请选择 LLM 提供商（数字）：")
    for i, (name, _url, model, hint) in enumerate(PROVIDER_PRESETS, 1):
        print(f"    {i}. {name} — {hint}（默认模型: {model or '自定义'}）")
    print("    0. 跳过（稍后再配 API）")
    print()
    choice = _prompt("输入数字", "1")
    if choice == "0":
        return None, "", ""
    try:
        idx = int(choice) - 1
    except ValueError:
        idx = 0
    idx = max(0, min(idx, len(PROVIDER_PRESETS) - 1))
    name, base_url, model, _hint = PROVIDER_PRESETS[idx]
    print(f"  → 已选: {name}")
    if name == "自定义":
        base_url = _prompt("OPENAI_BASE_URL（可留空）", "")
        model = _prompt("BOBANANA_MODEL", "gpt-4o-mini")
    return base_url or None, model, name


def configure_api(
    *,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    skip_key: bool = False,
    non_interactive: bool = False,
    path: Path | None = None,
) -> bool:
    """Interactive or CLI API setup. Returns True if a key was saved."""
    ensure_env_file()
    path = path or ENV_FILE

    if non_interactive and skip_key and not api_key:
        print("[config] skipped API key — edit .env later")
        return False

    print()
    print("=" * 50)
    print("  BoBanana — 配置 LLM API（OpenAI 兼容）")
    print("=" * 50)
    print(f"  配置文件: {path}")
    print()

    if not non_interactive and not api_key and not skip_key:
        _base, _model, _name = _choose_provider()
        if _base is None and _model == "" and _name == "":
            print("[config] 已跳过 — 离线模式可用；联网任务前请再运行 bb config")
            return False
        if _base:
            base_url = _base
        if _model:
            model = _model

    if not api_key and not skip_key:
        print()
        print("  粘贴你的 API Key（输入时不会显示在屏幕上）。")
        print("  直接按 Enter = 跳过，稍后在 .env 里手动填写。")
        api_key = _prompt("OPENAI_API_KEY", "", secret=True)

    if api_key:
        set_env_value("OPENAI_API_KEY", api_key, path)
        print(f"[config] OPENAI_API_KEY = {mask_secret(api_key)}")

    if not non_interactive and not base_url and api_key:
        base_url = _prompt("OPENAI_BASE_URL（OpenAI 可留空）", get_env_value("OPENAI_BASE_URL", path) or "")

    if base_url:
        set_env_value("OPENAI_BASE_URL", base_url, path)
        print(f"[config] OPENAI_BASE_URL = {base_url}")

    if not model and api_key:
        model = _prompt("BOBANANA_MODEL", get_env_value("BOBANANA_MODEL", path) or "gpt-4o-mini")

    if model:
        set_env_value("BOBANANA_MODEL", model, path)
        print(f"[config] BOBANANA_MODEL = {model}")

    if not api_key:
        print("[config] 未设置 API Key — 可运行 `bb config` 或 `python -m bobanana --configure` 再配")
        return False
    return True


def print_env_summary(path: Path | None = None) -> None:
    path = path or ENV_FILE
    st = env_status(path)
    print()
    print("  当前配置摘要：")
    print(f"    OPENAI_API_KEY     = {mask_secret(st.get('OPENAI_API_KEY') or '')}")
    print(f"    OPENAI_BASE_URL    = {st.get('OPENAI_BASE_URL') or '(默认 OpenAI)'}")
    print(f"    BOBANANA_MODEL     = {st.get('BOBANANA_MODEL') or 'gpt-4o-mini'}")
    print()
