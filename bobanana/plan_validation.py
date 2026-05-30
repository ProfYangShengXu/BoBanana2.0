"""Deterministic plan validation: paths, phantoms, step count."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .state import Plan

ARCHITECTURE_MAX_STEPS = 8

# Paths that do not exist in BoBanana2.0 — plans must not reference them.
PHANTOM_PATHS = (
    "src/",
    "src\\",
    "agent/",
    "agents/plan_executor",
    "plan_executor.py",
    "base_tool.py",
    "package.json",
    "pyproject.toml",
    "Makefile",
)

_PATH_IN_BACKTICKS = re.compile(r"`([^`]+)`")
_PATH_AFTER_READ = re.compile(
    r"(?:read_file|list_dir|write_file)\s+[`']?([\w./\\-]+\.(?:py|md|txt|json|yaml|yml)|[\w./\\-]+/)",
    re.I,
)
_BOBANANA_PATH = re.compile(r"(bobanana/[\w./\\-]+|docs/[\w./\\-]+|tests/[\w./\\-]+)", re.I)


@dataclass
class PlanValidation:
    ok: bool
    unknown_paths: list[str] = field(default_factory=list)
    phantom_hits: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    step_count: int = 0
    has_deliverable_write: bool = False
    is_architecture_task: bool = False

    def report(self) -> str:
        lines = [
            f"ok={self.ok}",
            f"steps={self.step_count}",
            f"has_write_step={self.has_deliverable_write}",
        ]
        if self.phantom_hits:
            lines.append("phantom_paths: " + "; ".join(self.phantom_hits))
        if self.unknown_paths:
            lines.append("unknown_paths: " + "; ".join(self.unknown_paths[:8]))
        if self.warnings:
            lines.append("warnings: " + "; ".join(self.warnings))
        return "\n".join(lines)

    def error_messages(self) -> list[str]:
        out: list[str] = []
        for p in self.phantom_hits:
            out.append(f"Remove phantom path '{p}' — it does not exist in this repo.")
        for p in self.unknown_paths[:5]:
            out.append(f"Path '{p}' not found in workspace index; use Live index paths only.")
        for w in self.warnings:
            out.append(w)
        if self.is_architecture_task and self.step_count > ARCHITECTURE_MAX_STEPS:
            out.append(f"Architecture task has {self.step_count} steps; reduce to ≤{ARCHITECTURE_MAX_STEPS}.")
        if self.is_architecture_task and not self.has_deliverable_write:
            out.append("Architecture task must include a write_file step for the final report.")
        return out


def _is_architecture_task(user_request: str) -> bool:
    low = user_request.lower()
    return any(k in low for k in (
        "架构", "批判", "architecture", "critique", "review agent", "分析", "整体设计",
    ))


def extract_path_candidates(text: str) -> list[str]:
    found: list[str] = []
    for m in _PATH_IN_BACKTICKS.finditer(text):
        found.append(m.group(1).strip())
    for m in _PATH_AFTER_READ.finditer(text):
        found.append(m.group(1).strip())
    for m in _BOBANANA_PATH.finditer(text):
        found.append(m.group(1).strip())
    # dedupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for p in found:
        p = p.replace("\\", "/").strip().strip("'\"")
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _path_in_index(path: str, index_text: str, workspace: Path) -> bool:
    norm = path.replace("\\", "/").strip().lstrip("./")
    if norm in index_text or f"/{norm}" in index_text or f"{norm}\n" in index_text:
        return True
    full = (workspace / norm).resolve()
    if full.is_file() or full.is_dir():
        return True
    # parent dir exists
    if full.parent.exists() and full.name:
        return True
    return False


def _check_phantom(path: str) -> str | None:
    low = path.replace("\\", "/").lower()
    for ph in PHANTOM_PATHS:
        if ph.lower() in low or low.startswith(ph.lower().rstrip("/")):
            return ph
    return None


def validate_plan(
    plan: Plan,
    user_request: str,
    workspace: Path,
    index_text: str = "",
) -> PlanValidation:
    is_arch = _is_architecture_task(user_request)
    v = PlanValidation(
        ok=True,
        step_count=len(plan.steps),
        is_architecture_task=is_arch,
    )
    all_text = " ".join(s.description for s in plan.steps) + " " + user_request

    if "write_file" in all_text.lower() or "写入" in all_text or "write " in all_text.lower():
        v.has_deliverable_write = True
    for step in plan.steps:
        if re.search(r"\b(write|写入|创建.*\.md)\b", step.description, re.I):
            v.has_deliverable_write = True
            break

    for step in plan.steps:
        for cand in extract_path_candidates(step.description):
            ph = _check_phantom(cand)
            if ph:
                v.phantom_hits.append(cand)
                v.ok = False
                continue
            if cand and not _path_in_index(cand, index_text, workspace):
                # ignore vague globs
                if "*" in cand or "?" in cand:
                    continue
                if len(cand) > 2:
                    v.unknown_paths.append(cand)

    if v.unknown_paths:
        v.ok = False

    if is_arch and v.step_count > ARCHITECTURE_MAX_STEPS:
        v.ok = False
        v.warnings.append(f"Too many steps ({v.step_count}); max {ARCHITECTURE_MAX_STEPS} for architecture tasks.")

    if is_arch and not v.has_deliverable_write:
        v.warnings.append("Missing deliverable write_file step for report.")

    if is_arch:
        from .report_validation import extract_write_path, validate_architecture_deliverable_path

        for step in plan.steps:
            wp = extract_write_path(step.description)
            if wp:
                err = validate_architecture_deliverable_path(wp)
                if err:
                    v.warnings.append(err)
                    v.ok = False
        if "critique_report.md" in all_text.lower() and "docs/delivery/output/" not in all_text.lower():
            v.warnings.append("Do not use root critique_report.md; use docs/delivery/output/YYYY-MM-DD-architecture-critique.md")
            v.ok = False
        if "memory/manager.py" not in all_text and "memory/manager" not in all_text:
            v.warnings.append("Architecture plan must read bobanana/memory/manager.py")
            v.ok = False
        if "tests/" not in all_text and "test_features" not in all_text:
            v.warnings.append("Architecture plan must include tests/ (e.g. tests/test_features.py)")
            v.ok = False
        if "describe_tool_registry" not in all_text and "registry.py" not in all_text:
            v.warnings.append("Architecture plan must use describe_tool_registry or read bobanana/tools/registry.py")
            v.ok = False

    tool_reg = re.search(r"工具注册|tool registry|tools/", all_text, re.I)
    if tool_reg and "describe_tool_registry" not in all_text and "registry.py" not in all_text:
        v.warnings.append(
            "For tool registry analysis use describe_tool_registry or read bobanana/tools/registry.py; "
            "do not dir-scan .bobanana/tools/ alone."
        )

    if v.phantom_hits or (is_arch and v.step_count > ARCHITECTURE_MAX_STEPS):
        v.ok = False

    return v
