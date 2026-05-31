"""Tab completion for slash commands."""

from __future__ import annotations

from prompt_toolkit.completion import NestedCompleter, WordCompleter


def build_completer(app) -> NestedCompleter:
    chat_sub = WordCompleter(["new", "list", "switch", "kill", "rename", "delete"], ignore_case=True)
    skill_names = [s.name for s in app.skills.list()]
    session_ids = [s.id for s in app.session_manager.list_sessions()]

    base = {
        "/help": None,
        "/chat": chat_sub,
        "/open-folder": None,
        "/workspace": None,
        "/memory": None,
        "/recall": None,
        "/skills": None,
        "/skill": WordCompleter(skill_names, ignore_case=True) if skill_names else None,
        "/tools": None,
        "/reload-tools": None,
        "/mcp": None,
        "/load-agent-reach": None,
        "/debug": WordCompleter(["on", "off"], ignore_case=True),
        "/resume": None,
        "/rollback": None,
        "/undo": None,
        "/clear": None,
        "/clear-mind": None,
        "/clear mind": None,
        "/restart": None,
        "/quit": None,
        "/exit": None,
    }
    return NestedCompleter.from_nested_dict(base)


def prompt_label(app) -> str:
    rt = app.session_manager.focus
    if rt is None:
        return "bobanana> "
    short = rt.session.id[:6]
    tok = rt.session.token_input + rt.session.token_output
    return f"bobanana[{short}|tok:{tok}]> "
