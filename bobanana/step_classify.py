"""Deterministic step classification for workflow routing (G3, G4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .report_validation import is_report_deliverable_step

if TYPE_CHECKING:
    from .tools.registry import StepTouch

_READ_MARKERS = (
    "read_file",
    "grep_file",
    "list_dir",
    "阅读",
    "分析",
    "read-only",
    "read only",
    "只读",
    "探索",
    "explore",
    "调研",
    "inspect",
)

_WRITE_MARKERS = ("write_file", "edit_file")


def _desc_allows_collect_only_shell(low: str) -> bool:
    if "run_shell" not in low and "run shell" not in low:
        return True
    return "collect-only" in low or "--collect-only" in low


def _shell_cmd_is_collect_only(ran_line: str) -> bool:
    cmd = ran_line.lower()
    return "collect-only" in cmd or "--collect-only" in cmd


def _evidence_is_read_only(last_evidence: str) -> bool:
    if not last_evidence.strip():
        return False
    if "[wrote]" in last_evidence or "[edited]" in last_evidence:
        return False
    for line in last_evidence.splitlines():
        if line.startswith("[ran]") and not _shell_cmd_is_collect_only(line):
            return False
    return "[read]" in last_evidence or "[cached]" in last_evidence


def _step_had_writes(step_touches: list[StepTouch] | None) -> bool:
    if not step_touches:
        return False
    return any(getattr(t, "op", "") in ("write", "edit") for t in step_touches)


def is_analysis_only_step(
    step_description: str,
    *,
    step_touches: list[StepTouch] | None = None,
    last_evidence: str | None = None,
) -> bool:
    """Read-only analysis step: safe to skip LLM exec_review (G3).

    Conservative: no write/edit/shell (except collect-only in desc), not a report
    deliverable, and description or runtime evidence indicates read-only work.
    """
    desc = step_description or ""
    if is_report_deliverable_step(desc):
        return False

    low = desc.lower()
    if any(m in low for m in _WRITE_MARKERS):
        return False
    if not _desc_allows_collect_only_shell(low):
        return False

    if _step_had_writes(step_touches):
        return False

    ev = last_evidence or ""
    if ev and not _evidence_is_read_only(ev):
        return False

    desc_suggests_read = any(m.lower() in low for m in _READ_MARKERS)
    if desc_suggests_read:
        return True
    if ev and _evidence_is_read_only(ev):
        return True
    return False
