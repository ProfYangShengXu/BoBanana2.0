# 更新日志 — 2026-05-30 · multi-chat-v3

> **关联任务**：BoBanana 3.0 多会话并发、/chat 窗口、遗忘加载、无工具上限+重复微规划、多轮 plan、Tab 补全、Token 显示、/undo。
> **状态**：实施中

## 计划逻辑链

入口 TUI → SessionManager（多 ChatSession + 独立 memory/graph/checkpoint）→ TaskRunner 后台 submit → graph 变体 ReAct；executor 无 iter 上限、重复 sig≥3 微规划；directive 满足后 next_plan_round；write_file 前 TurnSnapshot；/undo 整轮恢复。

## 实施记录

| 时间 | 改动 |
|------|------|
| 2026-05-30 | sessions/tasks/telemetry/undo 模块；app/tui/graph/executor 改造 |

## 阶段二自查结论

- [x] SessionManager + turns 持久化 + hydrate_with_forgetting
- [x] TaskRunner 后台 submit + /chat 指令 + Tab 补全
- [x] SqliteSaver 每 session + 独立 graph
- [x] 移除 max_tool_iters 硬上限 + micro_replan + multi plan round
- [x] TokenUsageHandler + /undo TurnJournal
- [x] pytest 116 passed（offline）
