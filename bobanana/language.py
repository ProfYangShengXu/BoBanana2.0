"""Detect user language and build reply directives for agents."""

from __future__ import annotations

import re

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")


def is_chinese_dominant(text: str) -> bool:
    """True when the user message is primarily Chinese."""
    if not text or not text.strip():
        return False
    cjk = len(_CJK.findall(text))
    if cjk == 0:
        return False
    latin = len(re.findall(r"[a-zA-Z]", text))
    # Any meaningful Chinese input, or Chinese outweighs Latin letters.
    return cjk >= 2 or cjk > latin


def language_directive(user_request: str) -> str:
    """Append to system prompts so agents match the user's language."""
    if is_chinese_dominant(user_request):
        return (
            "\n\n【语言】用户使用中文。所有面向用户的自然语言输出"
            "（计划摘要、步骤描述、审查意见、建议、理由、最终总结）必须使用简体中文。"
            "代码、文件名、URL、命令行可保持英文。"
        )
    return (
        "\n\nMatch the user's language in all user-facing natural-language output "
        "(summaries, step descriptions, review text, final answer)."
    )
