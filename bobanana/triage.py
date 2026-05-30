"""Lightweight heuristics to decide when meta-prompting is worthwhile and
whether a request is a coding task (for the delivery-gate skill).

These are cheap, token-free gates run before any LLM call.
"""

from __future__ import annotations

import re

from .language import is_chinese_dominant

# Verbs/nouns that strongly imply a code-producing task.
_CODE_HINTS = (
    "code", "function", "class", "module", "script", "api", "endpoint", "bug",
    "refactor", "implement", "fix", "build", "compile", "test", "debug", "deploy",
    "feature", "library", "package", "repo", "file",
    "写", "实现", "重构", "修复", "修改", "编写", "代码", "函数", "类", "脚本",
    "接口", "模块", "项目", "功能", "文件", "构建", "编译", "调试", "部署", "开发",
)

# Multi-step agent work: search, fetch, clone, reports — not "coding" but needs tools.
_RESEARCH_HINTS = (
    "search", "github", "gitlab", "web", "fetch", "curl", "scrape", "crawl",
    "clone", "download", "investigate", "research", "compare", "ranking", "top ",
    "stars", "pypi", "npm", "调研", "搜索", "检索", "抓取", "爬", "对比", "排行",
    "最火", "热门", "最新", "整理成", "报告", "汇总",
)

_REPORT_HINTS = (
    "report", "markdown", "write", "output", "deliverable", "summary", "document",
    "docs/delivery", "delivery/output",
    "报告", "输出", "写入", "整理", "汇总", "文档", "交付",
)

_GREETING_HINTS = (
    "hello", "hi", "hey", "who are you", "what are you",
    "你好", "您好", "你是谁", "你是什么", "介绍一下你", "在吗",
)

_VAGUE_HINTS = (
    "somehow", "something", "maybe", "etc", "and so on", "make it better",
    "improve", "optimize", "clean up", "handle everything",
    "随便", "之类", "等等", "优化一下", "改好", "弄一下", "搞一下", "完善",
)


def _word_count(text: str) -> int:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[a-zA-Z]+", text))
    return cjk + latin


def is_greeting(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    low = stripped.lower()
    wc = _word_count(stripped)
    if wc > 14:
        return False
    for h in _GREETING_HINTS:
        if h in ("hello", "hi", "hey"):
            if wc <= 8 and re.search(rf"(?:^|\b){re.escape(h)}(?:\b|$)", low):
                return True
        elif h in stripped or h in low:
            if wc <= 10:
                return True
    return False


def is_code_task(text: str) -> bool:
    low = text.lower()
    return any(h in low for h in _CODE_HINTS)


def needs_agent_pipeline(text: str) -> bool:
    """True when the task needs the full plan/execute tool loop (not chit-chat)."""
    if is_code_task(text):
        return True
    low = text.lower()
    return any(h in low for h in _RESEARCH_HINTS) or any(h in low for h in _REPORT_HINTS)


def looks_research_task(text: str) -> bool:
    """Search/fetch/compare tasks that usually need several tool steps."""
    low = text.lower()
    has_research = any(h in low or h in text for h in _RESEARCH_HINTS)
    has_report = any(h in low or h in text for h in _REPORT_HINTS)
    multi_clue = _word_count(text) >= 10 or has_report or "top" in low or "最" in text
    return has_research and multi_clue


def looks_large(text: str) -> bool:
    wc = _word_count(text)
    conj = len(re.findall(r"\band\b|、|，|,|；|;|\band then\b|然后|并且|以及", text))
    bullets = len(re.findall(r"\n\s*[-*\d]", text))
    return wc >= 40 or conj >= 3 or bullets >= 2


def looks_unclear(text: str) -> bool:
    low = text.lower()
    if any(h in low for h in _VAGUE_HINTS):
        return True
    if needs_agent_pipeline(text) and _word_count(text) <= 4:
        return True
    return False


def should_metaprompt(text: str) -> bool:
    return looks_large(text) or looks_unclear(text)


def estimate_task_size(text: str) -> float:
    """Token-free difficulty floor in [0, 1]. Intent layer may raise LLM estimates to this."""
    if is_greeting(text):
        return 0.0
    if looks_large(text):
        return 0.85
    if looks_research_task(text):
        return 0.62
    if needs_agent_pipeline(text):
        return 0.52
    if is_code_task(text):
        return 0.48 if looks_unclear(text) else 0.42
    if _word_count(text) <= 8:
        return 0.12
    return 0.25


def triage_reason(text: str) -> str:
    parts = []
    if looks_unclear(text):
        parts.append("unclear/under-specified")
    if looks_large(text):
        parts.append("large/multi-part")
    if looks_research_task(text):
        parts.append("research/multi-step")
    lang = "zh" if is_chinese_dominant(text) else "other"
    return f"{', '.join(parts) or 'ok'} (lang={lang})"
