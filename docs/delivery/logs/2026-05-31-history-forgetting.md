# 2026-05-31 对话历史加载 + 记忆遗忘

## §1 计划更新

**目标**
- 启动/切换窗口时加载并展示持久化对话历史（`turns.jsonl`）
- 完善遗忘机制：加载时摘要 + 运行时超阈值自动遗忘 + `/forget` 手动触发

**改动范围**

| 模块 | 变更 |
|------|------|
| `sessions/forgetting.py` | 增强 hydrate、新增 runtime 遗忘与历史摘要格式化 |
| `sessions/manager.py` | `reload_history`、`apply_forgetting`；append 后自动遗忘 |
| `memory/manager.py` | `build_context` 注入 session 摘要 |
| `tui.py` | 启动展示、`/history`、`/forget`；quick chat 走 append_turn |
| `tui_completer.py` | 补全 |
| `tests/test_sessions.py` | 回归 |

**明确不做**
- LLM 生成式摘要（仍用 rule_summarize 离线安全）
- 修改 turns.jsonl 物理删除旧轮（仅工作记忆遗忘，磁盘保留全量）

## §2 目标逻辑链

1. **持久化** → `SessionStore.append_turn` 写 `turns.jsonl` ✓ 已有
2. **加载** → `hydrate_with_forgetting` 最近 N 轮 + 远期摘要 fact ✓ 增强注入 working
3. **展示** → TUI 启动 / switch 打印历史摘要；`/history` 查看
4. **运行时遗忘** → 轮数 ≥ threshold 时 re-hydrate 压缩 working memory
5. **上下文** → `build_context` 优先包含 session 摘要 fact

**验收**
- 重启后 banner 下可见已加载历史提示
- `/history` 显示 turns.jsonl 最近条目
- 25+ 轮后 working 仅保留 recent + summary fact
- `/forget` 可手动触发
- 124+ tests pass

## §3 实施记录

| 时间 | 内容 |
|------|------|
| 2026-05-31 | 初版实现 |

## §4 自查结论

- 127 tests passed；`--selfcheck` 全 PASS
- 启动/switch 加载 turns.jsonl 并展示摘要；`/history`、`/forget` 可用
- 超 threshold 自动遗忘；摘要进入 `build_context`

---

# 追加（同日）：乱码 + Ctrl+C 失效修复

## 根因（runtime 证据：docs/delivery/output/5.31-2.md）

1. **乱码 `?[2;36m`**：TUI `patch_stdout()` 默认 `raw=False`，prompt_toolkit `Windows10_Output.write()` 会把 Rich 输出里的 ESC(0x1b) 转义成可见 `?`，导致 `\x1b[2;36m` → `?[2;36m`。prompt 外直接 `console.print`（如"已取消"）走真实 VT console 正常。
2. **Ctrl+C 失效**：`session.prompt()` 抛 KeyboardInterrupt 仅到主线程；后台 worker 线程的 `graph._stream` 无协作式取消标志，任务继续跑。

## 修复

| 文件 | 变更 |
|------|------|
| `tui.py` | `_read_line`/`_drain_focus_events` 的 `patch_stdout()` → `patch_stdout(raw=True)`；`_handle_keyboard_interrupt` 检测运行中任务则 set cancel event |
| `graph.py` | `_cancel_event` + `set_cancel_event`；`_stream` 每个 super-step 检查 |
| `sessions/manager.py` | `SessionRuntime.cancel_event` |
| `app.py` | worker 跑 graph 前 clear+wire cancel event；新增 `request_cancel` |

## §4 自查结论（追加）

逻辑链路自查（入口→校验→核心→副作用→失败/回滚）：

- **乱码**：入口=prompt 内后台刷新 → 核心=`patch_stdout(raw=True)` 让 Rich ANSI 原样透传，Windows10_Output.flush 自带 VT 开关 → 副作用=无（仅影响 prompt 期间的代理写入）→ 兜底=非 VT console 仍可读（仅退化为彩色丢失，本机 Win11 支持 VT）。
- **Ctrl+C**：入口=prompt KeyboardInterrupt → 校验=`request_cancel` 判 is_running → 核心=set `rt.cancel_event`，graph `_stream` 每 super-step 检查 → 副作用=worker 识别 interrupted 置状态、turn finalize、不追加 assistant turn；下次 submit `clear()`；resume 前 `clear()` 防旧标志复发 → 回滚=2s 内双击 Ctrl+C 仍退出程序。

验证：

- 129 passed（新增 `test_stream_respects_cancel_event`、`test_request_cancel_without_running_task`）
- `python -m bobanana --selfcheck` 全 PASS；import 烟测 OK；IDE 静态检查 clean
- TUI 交互（乱码消失 / Ctrl+C 停任务）需用户在真实终端确认（工具沙箱无真实 console，prompt_toolkit 无法初始化）

---

# 追加（同日）：TUI 交互层结构重构

## 为什么 TUI 反复出 bug（根因）

1. **`/chat switch` 是死代码**：`if sub == "switch"` 被错误缩进到 `if sub == "new"` 的 `return` 之后，切窗核心命令静默失效。
2. **巨型 if/elif + startswith 阶梯**：`_run_repl` 90 行手写分发，靠缩进/顺序维持正确性，`startswith("/skill")` 会误吃 `/skills`，缩进 bug 易溜入。
3. **三份真相源漂移**：dispatch / HELP / completer 各自手工维护。
4. **同步→异步半迁移残留**：`_run_task`、`_handle_interrupt` 等。

## 修复

| 文件 | 变更 |
|------|------|
| `tui.py` | `_cmd_chat` switch 去缩进（修死代码）；新增 `_build_commands` 命令注册表 + `_dispatch`（按首 token 精确路由，根除前缀/顺序/缩进类 bug）；`_run_repl` 90 行阶梯 → 一行 `_dispatch`；抽 `_print_help`/`_cmd_open_alias`/`_cmd_clear` |
| `tests/test_sessions.py` | +4 dispatch 测试（switch 可达、skill/skills 不撞、quit 退出、未知命令） |

## §4 自查（追加）

- 逻辑链：输入→`_dispatch` 首 token 查表→handler(arg, session)→返回 True 退出；非 `/` 前缀走 `_submit_task`。
- 副作用/回滚：命令集合与旧行为逐条对齐（`/chat` 空参列窗、`/clear mind`、`/open folder` 别名、`/clear-mind` 等均保留）。
- 133 passed；`--selfcheck` 全 PASS；静态检查 clean。

---

# 追加（同日）：执行器空转 + Ctrl+C 在节点内失效

## 根因（runtime 证据：用户贴的 22:19 循环日志）

1. **空转无"短思考"**：执行器在同一步反复发 `run_shell`（每条命令略不同、exit=0），而重复检测 `sig_counts` 只按**精确签名**计数 → 签名各异 → 永不到阈值 → 只能等 200 轮/600s 安全熔断。缺少"调用很多次仍未完成就反思/停止"的机制。
2. **Ctrl+C 没停**：取消标志只在 graph 超步（节点）之间检查，而死循环全在 `execute` 节点内部的 `while` 循环里 —— 执行器不返回，`_stream` 拿不到快照，取消检查到不了。

## 修复

| 文件 | 变更 |
|------|------|
| `agents/executor.py` | `execute` 新增 `cancel_event` 参数：循环顶部 + 每次工具调用后检查 → 立即返回 `Step stopped: cancelled by user.`；新增 `stall_reflect`（到 N 轮注入一次"停下来反思"提示=短思考）+ `stall_cap`（到上限返回 `Step stopped: no progress`，复用 review/advance 机制，避免 micro-replan 乒乓） |
| `graph.py` | 构造 executor 传 `stall_reflect/stall_cap`；`_execute_node` 调 `execute` 传 `cancel_event=self._cancel_event` |
| `config.py` / `.env.example` | 新增 `executor_stall_reflect=10`、`executor_stall_cap=20`（+ 环境变量） |
| `tests/` | +stall_cap 打破变化命令循环、+executor 内部 cancel；修 1 处 fake `_Exec.execute` 签名 |

## §4 自查（追加）

- 链路：执行器内 `cancel_event.is_set()` 早返 → execute 节点产出快照 → `_stream` 检测取消 → `_mark_interrupted("user")`，exec_review 不再执行。
- 短思考：第 10 轮注入反思提示让模型收敛；仍不收敛则第 20 轮以 no-progress 收尾交 reviewer 裁决。
- 163 passed；`--selfcheck` 全 PASS；静态检查 clean。
- 交互验证（真实空转任务按 Ctrl+C 应在当前命令后中断；长时间空转应在 ~20 轮内自停）需用户终端确认。
