"""Workspace-scoped file operations.

All paths are resolved relative to the workspace root and rejected if they
escape it. This is a lightweight guard, not a real sandbox.
"""

from __future__ import annotations

from pathlib import Path


class PathOutsideWorkspace(Exception):
    pass


class FileOps:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def _resolve(self, rel_path: str) -> Path:
        candidate = (self.workspace / rel_path).resolve()
        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise PathOutsideWorkspace(
                f"Refusing to access '{rel_path}': outside workspace {self.workspace}"
            ) from exc
        return candidate

    def read_file(self, rel_path: str, max_chars: int = 20000) -> str:
        path = self._resolve(rel_path)
        if not path.exists():
            return f"ERROR: file not found: {rel_path}"
        if not path.is_file():
            return f"ERROR: not a file: {rel_path}"
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            return text[:max_chars] + f"\n... [truncated {len(text) - max_chars} chars]"
        return text

    def write_file(self, rel_path: str, content: str) -> str:
        path = self._resolve(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        lines = content.count("\n") + 1
        return f"OK: wrote {len(content)} chars ({lines} lines) to {rel_path}"

    def append_file(self, rel_path: str, content: str) -> str:
        path = self._resolve(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(content)
        return f"OK: appended {len(content)} chars to {rel_path}"

    def list_dir(self, rel_path: str = ".") -> str:
        path = self._resolve(rel_path)
        if not path.exists():
            return f"ERROR: path not found: {rel_path}"
        entries = []
        for child in sorted(path.iterdir()):
            if child.name in {".git", ".bobanana", "__pycache__"}:
                continue
            kind = "dir " if child.is_dir() else "file"
            entries.append(f"[{kind}] {child.relative_to(self.workspace)}")
        return "\n".join(entries) if entries else "(empty)"

    def line_count(self, rel_path: str) -> int:
        path = self._resolve(rel_path)
        if not path.is_file():
            return 0
        return path.read_text(encoding="utf-8", errors="replace").count("\n") + 1
