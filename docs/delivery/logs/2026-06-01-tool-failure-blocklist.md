# 工具永久失败黑名单（blocked_paths / shell stem）

> 背景：5.31-4 任务空转 — 工作区外 `/tmp`、幻径、变体 `run_shell (&& py/fi)` 反复重试。现有 err_counts 仅拦相同 ERROR 签名。

## §1 计划

| 项 | 内容 |
|----|------|
| 目标 | 永久失败路径/命令类禁止本任务内重试；变体 shell 按 stem 聚类 |
| 文件 | `tool_blocklist.py`（新）、`executor.py`、`graph.py`、`plan_validation.py`、测试 |
| 不做 | 跨任务持久化黑名单、允许列表变更 |

## §2 逻辑链

- graph `execute` 传入 `scratch` → executor 每次工具调用前 `check_blocked` → 命中则直接 ERROR（不调工具）
- 工具返回后 `record_failure` 识别 outside workspace / file not found / allowlist 等永久错误
- run_shell：stem 聚类（`cd ... && py` 等短尾）→ 同 stem 二次调用短路
- plan_validation：步骤含 `/tmp/` 或 `> /tmp` → warning + ok=False

## §3 实施记录

- 新增 `bobanana/tool_blocklist.py`：`record_tool_failure` / `check_tool_blocked` / `shell_failure_stem`（`&& <short-tail>` 聚类 py/fi/di/fo）
- `executor.execute(scratch=…)`：调用前短路、返回后记录；`graph._execute_node` 传入 scratch；workspace 切换时 `clear_blocklist`
- `plan_validation`：步骤含 `/tmp/` → warning + ok=False
- `reviewer`：blocked / 永久路径错误不得 approve
- 测试 +3；修复 fake `_Exec.execute` 签名

## §4 自查结论

| 环 | ✓ |
|----|---|
| 入口 | graph → executor + scratch |
| 校验 | 永久 ERROR 标记列表；路径规范化 |
| 核心 | 第二次同路径不调工具；shell 同 stem 不调工具 |
| 副作用 | scratch `_blocked_tool_paths` / `_blocked_shell_stems` |
| 失败 | 与 err_counts 叠加；blocked 返回稳定 ERROR 文案 |

**验证**：181 项中 179 passed（+3 新增）；2 failed 为报告日期 `2026-05-31` vs `2026-06-01` 环境项，与本次无关。`--selfcheck` PASS。
