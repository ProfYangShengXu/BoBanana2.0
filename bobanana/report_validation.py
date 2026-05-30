"""Deterministic validation for architecture critique reports."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .version import version_line

ARCHITECTURE_MAX_STEPS = 8
DELIVERABLE_DIR = "docs/delivery/output/"

_DATE_IN_TEXT = re.compile(r"(20\d{2})-(\d{2})(?:-(\d{2}))?")
_PATH_IN_BACKTICKS = re.compile(r"`((?:bobanana|docs|tests)/[\w./\\-]+)`")
_PATH_BARE = re.compile(r"\b((?:bobanana|docs|tests)/[\w./\\-]+\.(?:py|md|txt|yaml|yml))\b")

_PROPOSED_NEW_MARKERS = re.compile(
    r"新建|可命名为|建议新增|建议新建|proposed|new file|新增.*文件|可新增|可命名",
    re.I,
)

_TEST_COUNT_CLAIM = re.compile(r"(\d+)\s*个测试")
_PYTEST_COLLECTED = re.compile(r"(\d+)\s+tests?\s+collected", re.I)

# Known false claims from prior bad runs (5.30-2 / 5.30-3 / 5.30-4).
FALSE_CLAIM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"ChromaDB|ChromaMemory|Chroma 向量|向量记忆.*Chroma|Chroma\)", "Chroma was removed; memory is working+structured only"),
    (r"memory\.store\s*\(|memory\.retrieve\s*\(", "MemoryManager has no store()/retrieve(); use remember_turn/build_context"),
    (r"工具注册机制缺失|没有.*ToolRegistry|工具完全硬编码", "Toolbox/registry.py and plugins exist"),
    (r"shell.*无超时|未设置.*timeout|无 timeout(?!\s*保护)", "ShellRunner has configurable timeout via Settings"),
    (r"无白名单|没有命令白名单|allows arbitrary shell", "Shell allowlist exists in shell_tools.py"),
    (r"\.bobanana/tools.*不存在|插件目录.*为空", ".bobanana/tools/ holds drop-in plugins"),
    (r"graph\.py.*(?:import|依赖).*app\.py|同时依赖了[^。\n]*app\.py", "graph.py does not import app.py"),
    (r"_create_graph\s*\(", "graph uses _build(), not _create_graph()"),
    (r"_build_graph\s*\(", "graph uses _build(), not _build_graph()"),
    (r"无路径遍历|没有路径遍历|无路径防护|路径遍历无防护|path traversal.*(?:无|没有|未)",
     "FileOps._resolve() uses relative_to(workspace) — path traversal is guarded"),
    (r"config\.py.*未.{0,20}(?:读取|使用).*BOBANANA_SHELL_TIMEOUT|未从.{0,15}配置.{0,10}shell_timeout|shell_tools\.py.*未读取.*BOBANANA_SHELL_TIMEOUT",
     "Settings.load reads BOBANANA_SHELL_TIMEOUT and passes to Toolbox/ShellRunner"),
    (r"run_bobanana\s*\(", "No run_bobanana(); entry is Application + __main__.py"),
    (r"build_context.{0,40}list_symbols|list_symbols.{0,40}build_context|list_explorations\s*\(\)",
     "build_context only uses list_files + all_facts"),
    (r"MCP.*未集成|均未使用.*MCP|Toolbox.*均未.*MCP|MCP 客户端未集成", "MCP tools are registered in Toolbox via McpManager"),
    (r"(?:调用|使用|通过|calls?).{0,30}execute_tool\s*\(", "Toolbox has no execute_tool() method"),
    (r"plan_validation.*\(False,\s*reason\)", "validate_plan returns PlanValidation dataclass"),
    (r"(intent|metaprompter).{0,40}__init__|实例化.*(intent|metaprompter)", "graph.py does not construct intent/metaprompter in __init__"),
)

EXTERNAL_CLAIM_PATTERNS: tuple[str, ...] = (
    r"LangGraph\s+\d+\.\d+",
    r"pytest-cov",
    r"GitHub Actions.*configured",
)

_EXTERNAL_URL_SATISFIERS: dict[str, str] = {
    r"pytest-cov": r"pypi\.org/project/pytest-cov",
    r"LangGraph\s+\d+\.\d+": r"(?:langchain\.com|github\.com/langchain)",
    r"GitHub Actions.*configured": r"\.github/workflows/",
}

_NEGATION_IN_LINE = re.compile(
    r"没有|不存在|无此|does not have|no such|并非|不是.*方法|未使用|removed|已移除|was removed",
    re.I,
)

_MINOR_VIOLATION_MARKERS = (
    "pytest --collect-only -q was not run",
)

_FENCED_CODE_BLOCK = re.compile(r"```(?:\w+)?\s*\n(.*?)```", re.DOTALL)

# Snippets in fenced blocks must appear in task_read_paths sources (anti-pseudocode).
_PSEUDOCODE_TRIGGERS = (
    r"raise\s+ValueError\s*\(",
    r"_build_graph\s*\(",
    r"_load_plugins\s*\(",
    r"raise\s+ValueError\s*\(\s*f[\"']File not found",
)

_AGENT_HEADER = re.compile(r"^>\s*(?:\*\*)?Agent(?:\*\*)?\s*:\s*(.+)$", re.M | re.I)


@dataclass
class ReportValidation:
    ok: bool
    violations: list[str] = field(default_factory=list)
    needs_web: list[str] = field(default_factory=list)
    critical_violations: list[str] = field(default_factory=list)
    minor_violations: list[str] = field(default_factory=list)

    def report(self) -> str:
        lines = [f"ok={self.ok}"]
        if self.violations:
            lines.append("violations: " + "; ".join(self.violations[:10]))
        if self.needs_web:
            lines.append("needs_web: " + "; ".join(self.needs_web[:5]))
        if self.minor_violations:
            lines.append("minor: " + "; ".join(self.minor_violations[:5]))
        return "\n".join(lines)


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").strip().lstrip("./")


def get_task_read_paths(scratch: dict) -> list[str]:
    raw = scratch.get("task_read_paths", "[]")
    try:
        paths = json.loads(raw)
        return [normalize_path(p) for p in paths if isinstance(p, str)]
    except (json.JSONDecodeError, TypeError):
        return []


def append_task_read_path(scratch: dict, path: str) -> None:
    norm = normalize_path(path)
    if not norm or norm in (".", ""):
        return
    paths = get_task_read_paths(scratch)
    if norm not in paths:
        paths.append(norm)
    scratch["task_read_paths"] = json.dumps(paths)


def reset_task_read_paths(scratch: dict) -> None:
    scratch["task_read_paths"] = "[]"
    scratch.pop("deliverable_path", None)
    scratch.pop("pytest_collect_count", None)
    scratch.pop("deliverable_write_unlocked", None)


def is_deliverable_write_path(path: str, scratch: dict) -> bool:
    dp = normalize_path(scratch.get("deliverable_path", "") or "")
    return bool(dp) and normalize_path(path) == dp


def deliverable_write_blocked(scratch: dict, path: str) -> str | None:
    """Block write_file on deliverable until pytest --collect-only has run."""
    if not is_deliverable_write_path(path, scratch):
        return None
    if scratch.get("deliverable_write_unlocked") == "1":
        return None
    if get_pytest_collect_count(scratch) is not None:
        scratch["deliverable_write_unlocked"] = "1"
        return None
    return (
        "ERROR: before write_file on the architecture deliverable, run "
        "pytest --collect-only -q via run_shell (first tool call on this step)"
    )


def begin_deliverable_write_step(scratch: dict, *, revision: int) -> None:
    """Reset write gate on first attempt at the deliverable step."""
    if revision == 0:
        scratch.pop("deliverable_write_unlocked", None)
        scratch.pop("pytest_collect_count", None)


def get_pytest_collect_count(scratch: dict) -> int | None:
    raw = scratch.get("pytest_collect_count")
    if raw is None or raw == "":
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def record_pytest_collect_output(scratch: dict, shell_output: str) -> None:
    """Parse pytest --collect-only output and store count in scratch."""
    m = _PYTEST_COLLECTED.search(shell_output)
    if m:
        scratch["pytest_collect_count"] = m.group(1)
        scratch["deliverable_write_unlocked"] = "1"


def report_claims_test_count(text: str) -> bool:
    if _TEST_COUNT_CLAIM.search(text):
        return True
    return bool(re.search(r"test_features\.py.*测试|tests?/.*测试", text, re.I))


def is_blocked_md_read(path: str, scratch: dict) -> str | None:
    """Block reading unverified .md as ground truth during report tasks."""
    norm = normalize_path(path)
    if not norm.endswith(".md"):
        return None
    if norm == "critique_report.md" or norm.endswith("/critique_report.md"):
        return (
            "ERROR: critique_report.md is a stale unverified artifact — do not use as source. "
            "Read bobanana/*.py, tests/, and docs/PROJECT.md instead."
        )
    deliverable = normalize_path(scratch.get("deliverable_path", "") or "")
    if deliverable and norm == deliverable:
        return (
            "ERROR: do not read_file the deliverable before writing — compose the report "
            "from sources already read and write_file directly."
        )
    if norm.startswith("docs/delivery/output/") and norm.endswith(".md"):
        return (
            "ERROR: do not read prior delivery output .md as source — content is unverified. "
            "Use read_file on source code or run pytest --collect-only -q for test counts."
        )
    return None


def build_report_header(read_paths: list[str] | None = None) -> str:
    today = date.today().isoformat()
    paths = read_paths or []
    path_line = ", ".join(paths[:20]) if paths else "(none yet)"
    if len(paths) > 20:
        path_line += f" …(+{len(paths) - 20} more)"
    return (
        f"> Generated: {today}\n"
        f"> Agent: {version_line()}\n"
        f"> Paths reviewed this task: {path_line}\n"
    )


def is_report_deliverable_step(step_description: str) -> bool:
    low = step_description.lower()
    return "write_file" in low and (".md" in low or "报告" in step_description or "report" in low)


def extract_write_path(step_description: str) -> str | None:
    m = re.search(
        r"write_file\s+[`']?([\w./\\-]+\.md)",
        step_description,
        re.I,
    )
    if m:
        return normalize_path(m.group(1))
    m = re.search(r"`((?:docs/)?[\w./\\-]+\.md)`", step_description)
    return normalize_path(m.group(1)) if m else None


def resolve_deliverable_path(scratch: dict, plan_steps: list | None = None) -> str | None:
    """Deliverable path from scratch or last write step in plan."""
    dp = scratch.get("deliverable_path", "")
    if dp:
        return normalize_path(dp)
    if plan_steps:
        for step in reversed(plan_steps):
            desc = step.description if hasattr(step, "description") else step.get("description", "")
            if is_report_deliverable_step(desc):
                wp = extract_write_path(desc)
                if wp:
                    return wp
    return None


def _line_for_match(text: str, match: re.Match) -> str:
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    if end == -1:
        end = len(text)
    return text[start:end]


def _is_proposed_new_path(line: str, path: str) -> bool:
    """True when path appears as a suggested new file, not an existing reference."""
    if _PROPOSED_NEW_MARKERS.search(line):
        return True
    if re.search(rf"{re.escape(path)}.{0,20}(建议|新建|新增|proposed)", line, re.I):
        return True
    return False


def _line_negates_claim(line: str) -> bool:
    return bool(_NEGATION_IN_LINE.search(line))


def _external_claim_satisfied(text: str, pattern: str) -> bool:
    satisfier = _EXTERNAL_URL_SATISFIERS.get(pattern)
    if satisfier and re.search(satisfier, text, re.I):
        return True
    return False


def _normalize_code(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _load_read_sources(workspace: Path, read_paths: list[str]) -> dict[str, str]:
    sources: dict[str, str] = {}
    for p in read_paths:
        full = (workspace / p).resolve()
        if not full.is_file():
            continue
        try:
            sources[p] = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return sources


def _snippet_in_sources(snippet: str, sources: dict[str, str]) -> bool:
    norm = _normalize_code(snippet)
    if len(norm) < 24:
        return True
    merged = _normalize_code("\n".join(sources.values()))
    if norm in merged:
        return True
    # Line-level: every substantive code line must appear in some source file.
    for raw in snippet.splitlines():
        line = raw.strip()
        if len(line) < 16 or line.startswith("#"):
            continue
        line_norm = _normalize_code(line)
        if not any(line_norm in _normalize_code(body) for body in sources.values()):
            return False
    return True


def _collect_pseudocode_violations(
    text: str,
    read_paths: list[str],
    workspace: Path,
) -> list[str]:
    if not read_paths:
        return []
    sources = _load_read_sources(workspace, read_paths)
    if not sources:
        return []
    violations: list[str] = []
    for block in _FENCED_CODE_BLOCK.findall(text):
        triggered = [pat for pat in _PSEUDOCODE_TRIGGERS if re.search(pat, block, re.I)]
        if not triggered:
            continue
        if _snippet_in_sources(block, sources):
            continue
        preview = _normalize_code(block)[:80]
        violations.append(
            f"Pseudocode/fabricated snippet not found in read sources: `{preview}…`"
        )
    # Prose claiming raise ValueError(File not found) when no read source contains it.
    if re.search(r"raise\s+ValueError\s*\([^)]*File not found", text, re.I):
        if not any(re.search(r"raise\s+ValueError\s*\([^)]*File not found", s, re.I) for s in sources.values()):
            violations.append(
                "Likely false claim (registry/file tools return ERROR strings, not raise ValueError(File not found))"
            )
    return violations


def _check_agent_header(text: str) -> list[str]:
    from .version import __version__

    violations: list[str] = []
    m = _AGENT_HEADER.search(text)
    if not m:
        violations.append("Missing > Agent: header; use build_report_header() / version_line()")
        return violations
    agent_val = m.group(1).strip()
    expected_prefix = f"BoBanana {__version__}"
    if not agent_val.startswith("BoBanana ") or __version__ not in agent_val:
        violations.append(
            f"Agent header must start with '{expected_prefix}' (from version_line); got '{agent_val}'"
        )
    return violations


def _collect_path_violations(
    text: str,
    read_paths: list[str],
    workspace: Path,
) -> list[str]:
    violations: list[str] = []
    read_set = {normalize_path(p) for p in read_paths}

    for m in _PATH_IN_BACKTICKS.finditer(text):
        p = normalize_path(m.group(1))
        line = _line_for_match(text, m)
        if _is_proposed_new_path(line, p):
            continue
        full = (workspace / p).resolve()
        if p not in read_set and not full.is_file():
            violations.append(f"Cited path '{p}' was not read this task and does not exist")

    for m in _PATH_BARE.finditer(text):
        p = normalize_path(m.group(1))
        line = _line_for_match(text, m)
        if _is_proposed_new_path(line, p):
            continue
        full = (workspace / p).resolve()
        if p not in read_set and not full.is_file():
            violations.append(f"Cited path '{p}' was not read this task and does not exist")

    return violations


def _check_test_count_claim(text: str, scratch: dict | None) -> str | None:
    if not report_claims_test_count(text):
        return None
    collected = get_pytest_collect_count(scratch or {})
    if collected is None:
        return (
            "Test count claimed but pytest --collect-only -q was not run this task; "
            "run it via run_shell before writing counts"
        )
    m = _TEST_COUNT_CLAIM.search(text)
    if m:
        claimed = int(m.group(1))
        if claimed != collected:
            return f"Test count {claimed} disagrees with pytest collect ({collected})"
    return None


def split_validation_issues(v: ReportValidation) -> tuple[list[str], list[str]]:
    critical: list[str] = []
    minor: list[str] = []
    for viol in v.violations:
        low = viol.lower()
        if any(m in low for m in _MINOR_VIOLATION_MARKERS):
            minor.append(viol)
        else:
            critical.append(viol)
    return critical, minor


def validation_strict_ok(v: ReportValidation) -> bool:
    return v.ok and not v.needs_web


def validation_acceptable_ok(v: ReportValidation) -> bool:
    """Disk soft-pass: no violations and no unresolved needs_web."""
    if v.needs_web:
        return False
    if v.violations:
        return False
    return True


def remediable_validation_notes(v: ReportValidation, text: str, scratch: dict) -> list[str]:
    """Issues that a remedial step can fix (test counts, external URLs)."""
    notes: list[str] = []
    if v.needs_web:
        notes.append("Add official URLs (fetch_url) for external claims or remove them")
    if _check_test_count_claim(text, scratch) or any(
        "pytest" in x.lower() or "test count" in x.lower() for x in v.violations
    ):
        notes.append("Run pytest --collect-only -q and update test counts to match")
    return list(dict.fromkeys(notes))


def validate_report_content(
    text: str,
    read_paths: list[str],
    workspace: Path,
    *,
    today: date | None = None,
    scratch: dict | None = None,
) -> ReportValidation:
    today = today or date.today()
    today_str = today.isoformat()
    today_ym = today_str[:7]
    v = ReportValidation(ok=True)

    header = "\n".join(text.splitlines()[:40])
    for m in _DATE_IN_TEXT.finditer(header):
        found = m.group(0)
        if len(found) == 10 and found != today_str:
            v.violations.append(f"Wrong date '{found}' in report header; use {today_str}")
        elif len(found) == 7 and found != today_ym:
            v.violations.append(f"Wrong month '{found}' in report; use {today_ym}")
    for label in ("生成日期", "Generated:", "最后更新", "Last updated"):
        if label in text:
            idx = text.find(label)
            snippet = text[idx: idx + 80]
            for m in _DATE_IN_TEXT.finditer(snippet):
                if m.group(0) != today_str and len(m.group(0)) >= 7:
                    if m.group(0) != today_ym:
                        v.violations.append(
                            f"Date near '{label}' is '{m.group(0)}'; must be {today_str}"
                        )

    v.violations.extend(_collect_path_violations(text, read_paths, workspace))
    v.violations.extend(_check_agent_header(text))
    v.violations.extend(_collect_pseudocode_violations(text, read_paths, workspace))

    for pattern, reason in FALSE_CLAIM_PATTERNS:
        for m in re.finditer(pattern, text, re.I):
            line = _line_for_match(text, m)
            if _line_negates_claim(line):
                continue
            msg = f"Likely false claim ({reason})"
            if msg not in v.violations:
                v.violations.append(msg)
            break

    test_err = _check_test_count_claim(text, scratch)
    if test_err and test_err not in v.violations:
        v.violations.append(test_err)

    for pattern in EXTERNAL_CLAIM_PATTERNS:
        if re.search(pattern, text, re.I) and not _external_claim_satisfied(text, pattern):
            v.needs_web.append(f"UNVERIFIED_EXTERNAL: pattern `{pattern}` — use web_search or remove")

    v.critical_violations, v.minor_violations = split_validation_issues(v)
    if v.violations or v.needs_web:
        v.ok = False
    return v


def verify_deliverable_on_disk(
    path: str,
    workspace: Path,
    read_paths: list[str],
    *,
    max_excerpt: int = 4000,
    scratch: dict | None = None,
) -> tuple[bool, str, ReportValidation]:
    """Read deliverable from disk and validate. Returns (strict_ok, excerpt, validation)."""
    norm = normalize_path(path)
    full = (workspace / norm).resolve()
    empty_val = ReportValidation(ok=False, violations=["deliverable not on disk"])
    if not full.is_file():
        return False, "", empty_val
    try:
        body = full.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return False, "", ReportValidation(ok=False, violations=[f"cannot read deliverable: {exc}"])
    if len(body.strip()) < 50:
        return False, body[:200], ReportValidation(ok=False, violations=["deliverable empty or too short"])
    validation = validate_report_content(body, read_paths, workspace, scratch=scratch)
    excerpt = body[:max_excerpt]
    if len(body) > max_excerpt:
        excerpt += f"\n…(+{len(body) - max_excerpt} chars)"
    ok_disk = validation_strict_ok(validation)
    return ok_disk, excerpt, validation


def deliverable_disk_evidence_block(
    path: str,
    workspace: Path,
    read_paths: list[str],
    *,
    scratch: dict | None = None,
) -> str:
    """Deterministic evidence for directive_gate / finalize."""
    ok, excerpt, validation = verify_deliverable_on_disk(path, workspace, read_paths, scratch=scratch)
    acceptable = validation_acceptable_ok(validation)
    if not ok and not excerpt:
        return f"DELIVERABLE_ON_DISK: path={path} — NOT FOUND\n"
    return (
        f"DELIVERABLE_ON_DISK: path={path}\n"
        f"strict_ok={ok} acceptable_ok={acceptable}\n"
        f"validation:\n{validation.report()}\n"
        f"excerpt:\n{excerpt[:2000]}\n"
    )


def validate_architecture_deliverable_path(path: str) -> str | None:
    """Return error message if path is wrong for architecture report."""
    norm = normalize_path(path)
    if norm == "critique_report.md" or norm.endswith("/critique_report.md"):
        return "Write report under docs/delivery/output/, not critique_report.md at repo root"
    if not norm.startswith(DELIVERABLE_DIR):
        return f"Architecture report must be under {DELIVERABLE_DIR}"
    if not norm.endswith(".md"):
        return "Deliverable must be a .md file"
    return None
