"""Build DISK_REVIEW snapshots and deterministic code checks for exec_review."""

from __future__ import annotations

import ast
import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .tools.file_tools import FileOps

_STUB_ONLY = re.compile(
    r"^\s*(?:async\s+)?def\s+\w+\([^)]*\):\s*\n\s*(?:pass|\.\.\.)\s*(?:#.*)?$",
    re.MULTILINE,
)
_TODO_DENSE = re.compile(r"\b(?:TODO|FIXME)\b", re.I)


@dataclass
class StepTouch:
    path: str
    op: Literal["write", "edit"]


def _resolve(workspace: Path, path: str) -> Path:
    return (workspace / path).resolve()


def _read_file_text(full: Path) -> str | None:
    if not full.is_file():
        return None
    try:
        return full.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _is_large(lines: int, size: int, full_max_lines: int, full_max_bytes: int) -> bool:
    return lines > full_max_lines or size > full_max_bytes


def _truncate_diff(diff_lines: list[str], max_hunks: int) -> tuple[list[str], bool]:
    if max_hunks <= 0:
        return diff_lines, False
    out: list[str] = []
    hunks = 0
    truncated = False
    for line in diff_lines:
        if line.startswith("@@"):
            hunks += 1
            if hunks > max_hunks:
                truncated = True
                break
        out.append(line)
    if truncated:
        out.append(f"…(diff truncated after {max_hunks} hunks)")
    return out, truncated


def _build_diff(before: str, after: str, path: str, max_hunks: int) -> str:
    diff_lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )
    if not diff_lines:
        return "(no line changes detected)"
    diff_lines, _ = _truncate_diff(diff_lines, max_hunks)
    return "\n".join(diff_lines)


def run_deterministic_checks(
    touches: list[StepTouch],
    after_by_path: dict[str, str | None],
) -> tuple[str, bool]:
    violations: list[str] = []
    for touch in touches:
        after = after_by_path.get(touch.path)
        if after is None:
            violations.append(f"Missing file on disk after {touch.op}: {touch.path}")
            continue
        if not after.strip():
            violations.append(f"Empty file after {touch.op}: {touch.path}")
            continue
        if touch.path.endswith(".py"):
            try:
                ast.parse(after)
            except SyntaxError as exc:
                violations.append(
                    f"Syntax error in {touch.path} line {exc.lineno or '?'}: {exc.msg}"
                )
            if len(_STUB_ONLY.findall(after)) >= 2:
                violations.append(
                    f"Multiple stub-only functions (pass/...) in {touch.path}"
                )
            todo_count = len(_TODO_DENSE.findall(after))
            line_count = after.count("\n") + 1
            if todo_count >= 8 or (line_count < 80 and todo_count >= 4):
                violations.append(
                    f"Too many TODO/FIXME markers ({todo_count}) in {touch.path}"
                )
    if violations:
        return "\n".join(f"- {v}" for v in violations), False
    return "(code validation ok)", True


def build_review_snapshot(
    workspace: Path,
    touches: list[StepTouch],
    before: dict[str, str | None],
    *,
    review_enable: bool = True,
    full_max_lines: int = 400,
    full_max_bytes: int = 102_400,
    total_max_chars: int = 24_000,
    diff_max_hunks: int = 40,
    max_priority_files: int = 3,
) -> tuple[str, str, bool]:
    """Return (disk_review_md, deterministic_report, deterministic_ok)."""
    if not review_enable:
        return "", "", True
    if not touches:
        return "", "(no files touched this step)", True

    files = FileOps(workspace)
    after_by_path: dict[str, str | None] = {}
    sections: list[str] = []
    priority = touches[:max_priority_files] if len(touches) > 5 else touches
    deferred = touches[max_priority_files:] if len(touches) > 5 else []

    def _section_for(touch: StepTouch) -> str:
        full = _resolve(workspace, touch.path)
        after = _read_file_text(full)
        after_by_path[touch.path] = after
        if after is None:
            return f"#### {touch.path} [{touch.op}, MISSING]\n(file not found on disk)\n"

        lines = files.line_count(touch.path)
        size = full.stat().st_size if full.is_file() else 0
        prev = before.get(touch.path)
        large = _is_large(lines, size, full_max_lines, full_max_bytes)

        if not large:
            return (
                f"#### {touch.path} [{touch.op}, {lines} lines, FULL]\n"
                f"```\n{after}\n```\n"
            )

        if touch.op == "edit" and prev is not None:
            diff = _build_diff(prev, after, touch.path, diff_max_hunks)
            return (
                f"#### {touch.path} [edited, {lines} lines, DIFF]\n"
                f"```diff\n{diff}\n```\n"
            )

        if prev is None:
            tag = "NEW"
        else:
            tag = "wrote"
        outline = files.read_file(touch.path, mode="outline")
        return (
            f"#### {touch.path} [{tag}, {lines} lines, OUTLINE]\n"
            f"```\n{outline}\n```\n"
        )

    for touch in priority:
        sections.append(_section_for(touch))

    for touch in deferred:
        full = _resolve(workspace, touch.path)
        after = _read_file_text(full)
        after_by_path[touch.path] = after
        if after is None:
            sections.append(f"#### {touch.path} [{touch.op}, MISSING]\n")
        else:
            lines = files.line_count(touch.path)
            sections.append(
                f"#### {touch.path} [{touch.op}, {lines} lines, SUMMARY_ONLY]\n"
                "(omitted — over multi-file cap; see priority files above)\n"
            )

    disk_review = "\n".join(sections).strip()
    if len(disk_review) > total_max_chars:
        disk_review = (
            disk_review[:total_max_chars]
            + f"\n…(DISK_REVIEW truncated at {total_max_chars} chars)\n"
        )

    det_report, det_ok = run_deterministic_checks(touches, after_by_path)
    return disk_review, det_report, det_ok
