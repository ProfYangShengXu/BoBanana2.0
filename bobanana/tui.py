"""Forge-style pure-terminal interface (rich + prompt_toolkit)."""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .app import Application
from .version import version_line, version_short

BANNER = r"""
  ____       ____
 |  _ \      | __ )  __ _ _ __   __ _ _ __   __ _
 | |_) |____ |  _ \ / _` | '_ \ / _` | '_ \ / _` |
 |  _ <_____|| |_) | (_| | | | | (_| | | | | (_| |
 |____/      |____/ \__,_|_| |_|\__,_|_| |_|\__,_|  {ver}
"""

HELP = """\
命令一览（{ver_line}）：
  /help               显示本帮助
  /chat new [标题]    新建对话窗口并切换
  /chat list          列出所有窗口（id / 状态 / token）
  /chat switch <id|#> 跳转到指定窗口并回放最近输出
  /chat kill <id>     终止后台任务
  /chat rename <标题> 重命名当前窗口
  /chat delete <id>   删除窗口（需无运行中任务）
  /undo               撤销当前窗口最近一轮（文件+记忆+graph）
  /open-folder [路径] 选择代码工作区
  /workspace          显示当前工作区
  /memory             查看记忆摘要
  /recall <关键词>    关键词检索对话
  /skills             列出技能
  /skill <名称>       打印 SKILL.md
  /tools              工具注册表
  /reload-tools       热加载插件
  /mcp                MCP 状态
  /load-agent-reach   克隆 Agent-Reach
  /debug [on|off]     调试日志
  /resume             继续当前窗口中断的任务
  /rollback [编号]    回退检查点
  /clear mind          清空任务污染记忆
  /clear               清空工作记忆含 scratch
  /restart            重启程序
  /quit, /exit        退出

普通输入提交到**当前窗口**后台执行（可同时跑多个窗口，/chat list 查看）。
Tab 补全 slash 命令。提示符显示 [窗口id|tok:累计token]。
"""


class TerminalUI:
    def __init__(self, app: Application) -> None:
        self.app = app
        self.console = Console()
        self._session = None

    # ----- event rendering -----
    def render_event(self, event: dict) -> None:
        kind = event.get("kind")
        if kind == "plan":
            self._render_plan(event)
        elif kind == "plan_review":
            self._render_review(event["review"], title="Plan review")
        elif kind == "step_start":
            self.console.rule(f"[bold cyan]Step {event['index']}/{event['total']}[/]")
            self.console.print(Text(event["description"], style="cyan"))
        elif kind == "tool":
            self._render_tool(event)
        elif kind == "step_output":
            self.console.print(Panel(Markdown(event["output"]), title="executor", border_style="green"))
        elif kind == "exec_review":
            self._render_review(event["review"], title=f"Step {event['index']} review")
        elif kind == "directive_gate":
            self._render_directive_gate(event)
        elif kind == "replan":
            self.console.print(Panel(
                f"shell command timed out — revising the plan (rev {event.get('revision', '?')}).\n"
                f"[dim]{event.get('detail', '')}[/]",
                title="Replanning (timeout)", border_style="yellow"))
        elif kind == "difficulty":
            self.console.print(
                f"[dim]难度上调 → {event.get('value', 0):.2f}（本步工具预算 +{event.get('tool_iter_bonus', 0)}）"
                f" {event.get('reason', '')}[/]")
        elif kind == "interrupted":
            self.console.print(Panel(
                f"任务已中断（原因：{event.get('reason')}），进度停在第 {event.get('current_step', 0)} 步。",
                title="已中断", border_style="bold yellow"))
        elif kind == "rollback":
            self.console.print(f"[dim]回退到检查点 {event.get('checkpoint_id')} 并继续…[/]")
        elif kind == "final":
            status = event.get("status", "completed")
            if status == "partial":
                title, border = "Result · PARTIAL (unresolved items)", "bold yellow"
            else:
                title, border = "Result · completed", "bold magenta"
            self.console.print(Panel(Markdown(event["summary"]), title=title, border_style=border))
        elif kind == "micro_replan":
            self.console.print(Panel(
                f"重复工具调用 {event.get('sig', '?')} — 无审查微规划调整步骤 {event.get('step')}",
                title="Micro replan", border_style="yellow"))
        elif kind == "plan_round":
            self.console.print(f"[cyan]▶ 规划第 {event.get('round')} 轮[/]")
        elif kind == "token_usage":
            self.console.print(
                f"[dim]tokens +{event.get('input', 0)}/{event.get('output', 0)} "
                f"(Δ{event.get('total', 0)})[/]")
        elif kind == "error":
            self.console.print(Panel(str(event.get("message", "?")), title="Error", border_style="red"))

    def _render_plan(self, event: dict) -> None:
        plan = event["plan"]
        table = Table(title=f"Plan (rev {event.get('revision', 0)}) — {plan.get('summary', '')}",
                      show_header=True, header_style="bold")
        table.add_column("#", style="dim", width=3)
        table.add_column("Step")
        for step in plan.get("steps", []):
            table.add_row(str(step["id"]), step["description"])
        self.console.print(table)

    def _render_review(self, review: dict, title: str) -> None:
        verdict = "[green]APPROVED[/]" if review.get("approved") else "[yellow]NEEDS WORK[/]"
        lines = [f"{verdict}  score={review.get('score', 0)}/10"]
        if review.get("rationale"):
            lines.append(f"[dim]{review['rationale']}[/]")
        for s in review.get("suggestions", []):
            lines.append(f"  • {s}")
        self.console.print(Panel("\n".join(lines), title=title, border_style="yellow"))

    def _render_directive_gate(self, event: dict) -> None:
        check = event.get("check", {})
        ok = check.get("all_satisfied")
        verdict = "[green]ALL DIRECTIVES MET[/]" if ok else "[yellow]DIRECTIVES UNMET[/]"
        lines = [verdict]
        if check.get("notes"):
            lines.append(f"[dim]{check['notes']}[/]")
        for u in check.get("unmet", []):
            lines.append(f"  • {u}")
        self.console.print(Panel("\n".join(lines), title="Directive gate", border_style="magenta"))

    def _render_tool(self, event: dict) -> None:
        args = event.get("args", {})
        arg_preview = ", ".join(f"{k}={str(v)[:40]}" for k, v in args.items())
        result = str(event.get("result", ""))
        if len(result) > 300:
            result = result[:300] + " …"
        self.console.print(
            Text("  ↳ ", style="dim") + Text(f"{event['name']}({arg_preview})", style="bold blue")
        )
        self.console.print(Text("    " + result.replace("\n", "\n    "), style="dim"))

    # ----- commands -----
    def _cmd_memory(self) -> None:
        summary = self.app.memory.summary()
        self.console.print(Panel(str(summary), title="Memory summary", border_style="blue"))
        files = self.app.memory.structured.list_files()
        if files:
            t = Table(title="Tracked files", show_header=True)
            t.add_column("path")
            t.add_column("lines", justify="right")
            t.add_column("summary")
            for r in files[:30]:
                t.add_row(r["path"], str(r["lines"]), r["summary"])
            self.console.print(t)
        facts = self.app.memory.structured.all_facts()
        if facts:
            t = Table(title="Facts", show_header=True)
            t.add_column("category")
            t.add_column("key")
            t.add_column("value")
            for k, v, cat in facts[:30]:
                t.add_row(cat, k, v)
            self.console.print(t)

    def _cmd_recall(self, query: str) -> None:
        out = self.app.memory.recall_conversation(query, k=6)
        self.console.print(Panel(out or "(no matches)", title=f"Recall: {query}", border_style="blue"))

    def _cmd_skills(self) -> None:
        skills = self.app.skills.list()
        if not skills:
            self.console.print("[dim](no skills discovered)[/]")
            return
        t = Table(title="Adaptable skills", show_header=True)
        t.add_column("name", style="bold")
        t.add_column("description")
        t.add_column("source", style="dim")
        for s in skills:
            t.add_row(s.name, s.description, str(s.root))
        self.console.print(t)

    def _cmd_skill(self, name: str) -> None:
        if not name:
            self.console.print("[red]usage: /skill <name>[/]")
            return
        self.console.print(Panel(Markdown(self.app.skills.read(name)),
                                 title=f"Skill: {name}", border_style="green"))

    def _cmd_mcp(self) -> None:
        tools = ", ".join(getattr(t, "name", "?") for t in self.app._mcp_tools) or "(none)"
        self.console.print(Panel(f"status: {self.app.mcp.status}\ntools: {tools}",
                                 title="MCP", border_style="blue"))

    def _cmd_tools(self) -> None:
        from .tools import Toolbox

        cat = self.app.list_tools()
        t = Table(title=f"Executor tools ({Toolbox.REGISTRY_MODULE})", show_header=True, header_style="bold")
        t.add_column("name", style="cyan")
        t.add_column("ver", width=7)
        t.add_column("source")
        t.add_column("permissions")
        t.add_column("description", max_width=50)
        for entry in cat:
            t.add_row(
                entry["name"],
                entry.get("version", "?"),
                entry["source"],
                entry.get("permissions", ""),
                (entry.get("description") or "")[:120],
            )
        self.console.print(t)
        tb = self.app._make_toolbox()
        self.console.print(
            f"[dim]plugin_dir={tb.plugin_dir} · granted=[{', '.join(p.value for p in tb.permission_policy.granted)}] · "
            "用 describe_tool_registry 工具或 /tools 内省，勿仅凭 dir 扫描推断。[/]"
        )

    def _cmd_reload_tools(self) -> None:
        with self.console.status("[bold green]reloading plugins…", spinner="dots"):
            result = self.app.reload_tools()
        style = "green" if result.startswith("OK") else "red"
        self.console.print(Panel(result, title="reload-tools", border_style=style))

    def _cmd_load_agent_reach(self) -> None:
        with self.console.status("[bold green]cloning Agent-Reach…", spinner="dots"):
            result = self.app.load_agent_reach()
        style = "green" if result.startswith("OK") else "red"
        self.console.print(Panel(result, title="load-agent-reach", border_style=style))

    def _cmd_debug(self, arg: str) -> None:
        from .logging_setup import set_level

        on = arg.strip().lower() in ("", "on", "true", "1")
        set_level("DEBUG" if on else "INFO")
        self.console.print(f"[dim]debug logging {'ON' if on else 'OFF'}[/]")

    def _cmd_open_folder(self, arg: str) -> None:
        from .workspace import pick_directory, validate_directory

        arg = arg.strip()
        if arg:
            path, msg = validate_directory(arg)
            if path is None:
                self.console.print(f"[red]{msg}[/]")
                return
        else:
            self.console.print("[dim]opening folder picker…[/]")
            path = pick_directory()
            if path is None:
                self.console.print("[yellow]no folder selected (picker cancelled or unavailable). "
                                   "Tip: /open-folder <path>[/]")
                return
        result = self.app.set_workspace(path)
        style = "green" if result.startswith("OK") else "red"
        self.console.print(Panel(result, title="workspace", border_style=style))

    def _cmd_workspace(self) -> None:
        self.console.print(Panel(f"workspace: {self.app.settings.workspace}\n"
                                 f"data dir:  {self.app.settings.data_dir}",
                                 title="workspace", border_style="blue"))

    def _cmd_restart(self) -> None:
        from .restart import restart

        self.console.print("[dim]restarting…[/]")
        self.app.close()
        try:
            restart()
        except OSError as exc:
            self.console.print(Panel(f"restart failed: {exc}", title="Error", border_style="red"))

    def _cmd_chat(self, arg: str) -> None:
        parts = arg.split(None, 1)
        sub = (parts[0] if parts else "").lower()
        rest = parts[1].strip() if len(parts) > 1 else ""
        sm = self.app.session_manager

        if sub in ("", "list"):
            sessions = sm.list_sessions()
            t = Table(title="Chat windows", show_header=True, header_style="bold")
            t.add_column("#", style="dim", width=3)
            t.add_column("id")
            t.add_column("title")
            t.add_column("status")
            t.add_column("tokens", justify="right")
            t.add_column("workspace", max_width=30)
            for i, s in enumerate(sessions):
                mark = "*" if s.id == sm.focus_id else " "
                tok = s.token_input + s.token_output
                t.add_row(f"{mark}{i}", s.id, s.title, s.status.value, str(tok),
                          str(s.workspace)[-30:])
            self.console.print(t)
            return

        if sub == "new":
            s = sm.create(rest or "")
            self.console.print(f"[green]new chat {s.id} — {s.title}[/]")
            return

        if sub == "switch":
            if not rest:
                self.console.print("[red]usage: /chat switch <id|#>[/]")
                return
            s = sm.switch(rest)
            if s is None:
                self.console.print(f"[red]unknown session: {rest}[/]")
                return
            self.console.print(f"[green]switched to {s.id} — {s.title}[/]")
            rt = sm.get(s.id)
            if rt:
                for ev in rt.event_buffer.tail(40):
                    self.render_event(ev)
            return

        if sub == "kill":
            if not rest:
                rest = sm.focus_id or ""
            if self.app.task_runner.kill(rest):
                self.console.print(f"[yellow]killed task on {rest}[/]")
            else:
                self.console.print(f"[dim]no running task for {rest}[/]")
            return

        if sub == "rename":
            if not rest:
                self.console.print("[red]usage: /chat rename <title>[/]")
                return
            sm.rename_focus(rest)
            self.console.print("[green]renamed[/]")
            return

        if sub == "delete":
            if not rest:
                self.console.print("[red]usage: /chat delete <id>[/]")
                return
            if self.app.task_runner.is_running(rest):
                self.console.print("[red]stop task first (/chat kill)[/]")
                return
            if sm.delete(rest):
                self.console.print(f"[green]deleted {rest}[/]")
            else:
                self.console.print(f"[red]unknown session {rest}[/]")
            return

        self.console.print("[red]usage: /chat new|list|switch|kill|rename|delete[/]")

    def _cmd_undo(self) -> None:
        result = self.app.undo_last_turn()
        style = "green" if result.startswith("OK") else "red"
        self.console.print(Panel(result, title="undo", border_style=style))

    def _drain_focus_events(self) -> None:
        rt = self.app.session_manager.focus
        if rt is None:
            return
        new, cursor = rt.event_buffer.drain_since(rt.event_cursor)
        rt.event_cursor = cursor
        for ev in new:
            self.render_event(ev)

    # ----- main loop -----
    def run(self) -> None:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory

        from .tui_completer import build_completer, prompt_label

        self.console.print(Text(BANNER.format(ver=version_short()), style="bold yellow"))
        self.console.print(f"[dim]{version_line()} · multi-chat · Tab 补全[/]")
        if not self.app.settings.has_llm:
            self.console.print("[yellow]No OPENAI_API_KEY set — live runs disabled.[/]")
        self.console.print("Type /help for commands. /chat list 查看窗口。\n")

        completer = build_completer(self.app)
        session: PromptSession = PromptSession(
            history=InMemoryHistory(),
            completer=completer,
            complete_while_typing=True,
        )
        self._session = session
        while True:
            self._drain_focus_events()
            try:
                text = session.prompt(prompt_label(self.app)).strip()
            except (EOFError, KeyboardInterrupt):
                self.console.print("\n[dim]bye[/]")
                break
            if not text:
                continue
            if text in ("/quit", "/exit"):
                break
            if text == "/help":
                self.console.print(HELP.format(ver_line=version_line()))
                continue
            if text.startswith("/chat"):
                self._cmd_chat(text[len("/chat"):].strip())
                continue
            if text == "/undo":
                self._cmd_undo()
                continue
            if text.startswith("/open-folder") or text.startswith("/open folder"):
                arg = text.split(None, 1)[1] if " " in text else ""
                # handle the two-word "/open folder <path>" spelling
                if text.startswith("/open folder"):
                    arg = text[len("/open folder"):].strip()
                self._cmd_open_folder(arg)
                continue
            if text == "/workspace":
                self._cmd_workspace()
                continue
            if text == "/memory":
                self._cmd_memory()
                continue
            if text.startswith("/recall"):
                self._cmd_recall(text[len("/recall"):].strip())
                continue
            if text == "/skills":
                self._cmd_skills()
                continue
            if text == "/tools":
                self._cmd_tools()
                continue
            if text == "/reload-tools":
                self._cmd_reload_tools()
                continue
            if text.startswith("/skill"):
                self._cmd_skill(text[len("/skill"):].strip())
                continue
            if text == "/mcp":
                self._cmd_mcp()
                continue
            if text == "/load-agent-reach":
                self._cmd_load_agent_reach()
                continue
            if text.startswith("/debug"):
                self._cmd_debug(text[len("/debug"):].strip())
                continue
            if text in ("/clear mind", "/clear-mind"):
                stats = self.app.memory.clear_mind()
                self.console.print(
                    f"[dim]mind cleared: turns={stats['turns_cleared']} "
                    f"exploration={stats['exploration_cleared']} facts={stats['facts_cleared']} "
                    f"(scratch index/catalog kept)[/]"
                )
                continue
            if text == "/clear":
                self.app.memory.working.clear()
                self.console.print("[dim]working memory cleared (including scratch)[/]")
                continue
            if text == "/restart":
                self._cmd_restart()
                continue
            if text == "/resume":
                self._cmd_resume()
                continue
            if text.startswith("/rollback"):
                self._cmd_rollback(text[len("/rollback"):].strip(), session)
                continue
            if text.startswith("/"):
                self.console.print(f"[red]unknown command: {text}[/] (try /help)")
                continue

            self._submit_task(text, session)

        self.app.close()

    def _submit_task(self, text: str, session=None) -> None:
        if not self.app.settings.has_llm:
            self.console.print("[red]Cannot run: no OPENAI_API_KEY configured.[/]")
            return

        rt = self.app.session_manager.focus
        if rt is None:
            self.console.print("[red]no active chat session[/]")
            return
        sid = rt.session.id

        if self.app.task_runner.is_running(sid):
            self.console.print("[yellow]当前窗口任务仍在运行 — /chat new 开新窗口或 /chat kill[/]")
            return

        intent = self._intent_and_budget(text, session, rt) if session is not None else None

        if intent is not None and intent.task_size < 0.12 and not intent.is_code_task:
            try:
                with self.console.status("[bold green]…", spinner="dots"):
                    reply = self.app.chat_reply(text, rt)
                self.console.print(Panel(Markdown(reply), title="BoBanana", border_style="cyan"))
                rt.store.append_turn("user", text)
                rt.store.append_turn("assistant", reply)
            except Exception as exc:
                self.console.print(Panel(f"{type(exc).__name__}: {exc}", title="Error", border_style="red"))
            return

        difficulty = intent.task_size if intent is not None else 0.5
        if session is not None:
            if intent is not None:
                should_meta = intent.needs_metaprompt
            else:
                from .triage import should_metaprompt
                should_meta = should_metaprompt(text)
            final = self._maybe_metaprompt(text, session, should_meta)
            if final is None:
                return
            text = final

        try:
            self.app.submit_task(sid, text, on_event=self.render_event, difficulty=difficulty)
            self.console.print(f"[dim]task started on [{sid[:6]}] — /chat list 查看状态[/]")
        except Exception as exc:
            self.console.print(Panel(f"{type(exc).__name__}: {exc}", title="Error", border_style="red"))

    def _run_task(self, text: str, session=None) -> None:
        """Sync run (legacy / interrupt handler)."""
        self._submit_task(text, session)

    def _maybe_metaprompt(self, text: str, session, should_run: bool) -> str | None:
        """Run meta-prompting for large/unclear tasks.

        ``should_run`` is decided by the intent layer (with a heuristic fallback).
        Returns the (possibly refined) request to execute, or None to abort.
        """
        if not self.app.settings.enable_metaprompt or not should_run:
            return text

        self.console.print("[dim]meta-prompting (intent: task needs refinement)…[/]")
        try:
            with self.console.status("[bold green]assessing task…", spinner="dots"):
                triage = self.app.triage_task(text)
        except Exception as exc:
            self.console.print(f"[yellow]meta-prompt skipped: {type(exc).__name__}: {exc}[/]")
            return text

        if triage.needs_clarification and triage.questions:
            lines = [f"  {i}. {q}" for i, q in enumerate(triage.questions, 1)]
            self.console.print(Panel("\n".join(lines),
                                     title="Need a bit more detail", border_style="yellow"))
            try:
                answer = session.prompt("clarify> ").strip()
            except (EOFError, KeyboardInterrupt):
                self.console.print("[dim]cancelled[/]")
                return None
            if not answer:
                self.console.print("[dim]no clarification given — proceeding with original request[/]")
                return text
            return f"{text}\n\n[澄清/Clarification]\n{answer}"

        refined = (triage.refined_request or "").strip()
        if refined and refined != text.strip():
            self.console.print(Panel(refined, title="Refined task", border_style="cyan"))
            if triage.assessment:
                self.console.print(f"[dim]{triage.assessment}[/]")
            return refined
        return text

    def _intent_and_budget(self, text: str, session, rt=None):
        if not self.app.settings.enable_intent:
            return None
        try:
            with self.console.status("[bold green]reading intent…", spinner="dots"):
                intent = self.app.classify_intent(text, rt)
        except Exception as exc:
            self.console.print(f"[yellow]intent skipped: {type(exc).__name__}: {exc}[/]")
            return None
        scaled = self.app.apply_budget(intent.task_size, text, rt)
        self.console.print(
            f"[dim]intent: size={intent.task_size:.2f} code={intent.is_code_task} "
            f"steps≤{scaled['max_steps']} — {intent.reason}[/]")
        return intent

    def _handle_interrupt(self, session) -> None:
        """After a timeout/Ctrl-C interrupt, ask the user how to proceed."""
        self.console.print(Panel(
            "任务被中断，已保存检查点。\n"
            "  [bold]c[/] 继续    [bold]r[/] 回退到更早的检查点    [bold]a[/] 放弃\n"
            "  或直接输入新的指令来替换当前任务。",
            title="等待指令", border_style="yellow"))
        if session is None:
            return
        try:
            choice = session.prompt("interrupted> ").strip()
        except (EOFError, KeyboardInterrupt):
            self.console.print("[dim]已放弃该任务[/]")
            return
        if not choice or choice.lower() == "a":
            self.console.print("[dim]已放弃该任务[/]")
            return
        if choice.lower() == "c":
            self._cmd_resume()
            return
        if choice.lower() == "r":
            self._cmd_rollback("", session)
            return
        # Anything else: treat as a brand-new instruction.
        self._run_task(choice, session)

    def _cmd_resume(self) -> None:
        if not getattr(self.app, "_graph", None) or not self.app._graph.interrupted:
            self.console.print("[dim]没有可继续的中断任务[/]")
            return
        try:
            with self.console.status("[bold green]continuing…  [dim](Ctrl-C 中断)[/]", spinner="dots"):
                result = self.app.resume_task(on_event=self._event_under_status)
        except Exception as exc:
            self.console.print(Panel(f"{type(exc).__name__}: {exc}", title="Error", border_style="red"))
            return
        if result and result.get("interrupted"):
            self._handle_interrupt(self._session)

    def _cmd_rollback(self, arg: str, session) -> None:
        cps = self.app.list_checkpoints()
        if not cps:
            self.console.print("[dim]没有可用的检查点（需先运行过任务且开启 checkpoints）[/]")
            return
        # Show only resumable checkpoints (those with pending work).
        usable = [c for c in cps if c.get("next")]
        if not usable:
            usable = cps
        if not arg:
            t = Table(title="检查点（可回退）", show_header=True, header_style="bold")
            t.add_column("#", style="dim", width=3)
            t.add_column("step")
            t.add_column("next")
            t.add_column("difficulty")
            for i, c in enumerate(usable):
                t.add_row(str(i), str(c.get("current_step")), ",".join(c.get("next") or []),
                          f"{c.get('difficulty') if c.get('difficulty') is not None else '-'}")
            self.console.print(t)
            self.console.print("[dim]用 /rollback <编号> 选择回退点[/]")
            return
        try:
            idx = int(arg)
            target = usable[idx]
        except (ValueError, IndexError):
            self.console.print(f"[red]无效编号: {arg}[/]")
            return
        try:
            with self.console.status("[bold green]rolling back…  [dim](Ctrl-C 中断)[/]", spinner="dots"):
                result = self.app.rollback_task(target["checkpoint_id"],
                                                on_event=self._event_under_status)
        except Exception as exc:
            self.console.print(Panel(f"{type(exc).__name__}: {exc}", title="Error", border_style="red"))
            return
        if result and result.get("interrupted"):
            self._handle_interrupt(session)

    def _event_under_status(self, event: dict) -> None:
        # Rendering while a status spinner is active is fine with rich.
        self.render_event(event)
