"""Build a compact live file tree for planner context (no shell, no LLM)."""

from __future__ import annotations

from pathlib import Path

_SKIP_DIRS = {
    ".git", ".venv", "__pycache__", "node_modules", "dist", ".pytest_cache",
    ".cursor", ".bobanana", "chroma",
}
_MAX_CHARS = 4000


def _should_skip(name: str) -> bool:
    return name.startswith(".") and name not in (".env.example",)


def build_workspace_index(workspace: Path, max_depth: int = 2) -> str:
    """Scan workspace and return a compact tree for prompt injection."""
    root = workspace.resolve()
    lines: list[str] = [f"## Live workspace index (root={root.name}/)", ""]

    def list_level(base: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(base.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            lines.append(f"{prefix}[permission denied]")
            return
        for p in entries:
            if p.name in _SKIP_DIRS or _should_skip(p.name):
                continue
            rel = p.relative_to(root).as_posix()
            if p.is_dir():
                lines.append(f"{prefix}{p.name}/")
                if depth < max_depth:
                    list_level(p, prefix + "  ", depth + 1)
            else:
                lines.append(f"{prefix}{p.name}")

    list_level(root, "", 0)
    text = "\n".join(lines)
    if len(text) > _MAX_CHARS:
        return text[:_MAX_CHARS] + "\n…(index truncated)"
    return text
