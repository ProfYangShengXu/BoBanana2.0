# 读写工具 ABCD 强化

> 计划：读写 ABCD 强化（不编辑 plan 文件）

## §1 计划

| 块 | 内容 |
|----|------|
| B5+B1 | `file_tools` 流式 offset/limit；>120 行或 >80KB 默认 outline |
| B2 | `grep_file`（rg / findstr fallback） |
| C | `_write_guard` 拒绝巨型覆盖；`allow_full_write` 交付步豁免 |
| B4 | `_cache_get` 仅返回 stub；executor `[cached]` 一律 nonproductive |
| D | `_reads_this_task` / `_grep_recent` + `build_context` 提示 |
| A | 工具描述、planner、README/PROJECT |

## §2 逻辑链

grep_file → read_file(offset/limit|outline) → exploration DB 存全文 / ToolMessage 仅 stub → edit_file 改码 → write_file 护栏 → scratch 已读提示防重复读

## §3 实施记录

| 文件 | 变更 |
|------|------|
| `bobanana/tools/file_tools.py` | outline、`_read_line_window`、`_count_lines`、`grep_file` |
| `bobanana/tools/registry.py` | ReadArgs.mode、GrepArgs、stub 缓存、write guard、scratch 记录 |
| `bobanana/agents/executor.py` | `[cached]` 恒 nonproductive |
| `bobanana/memory/manager.py` | build_context 已读/grep 提示 |
| `bobanana/report_validation.py` | reset 清理 scratch；deliverable 设 `allow_full_write` |
| `bobanana/graph.py` | `begin_deliverable_write_step(..., deliverable_path=)` |
| `bobanana/agents/planner.py` | grep_file 工作流一句 |
| `bobanana/tool_blocklist.py` | clear 时清 reads/grep/allow_full_write |
| `tests/test_features.py` | +7 项 ABCD 测试；缓存测试改 stub 期望 |
| `docs/PROJECT.md` / `README.md` | 读写惯例 |
| `bobanana/version.py` | RELEASE_DATE → 2026-06-01（报告日期校验） |

## §4 自查结论

- 入口→校验→读盘/搜→缓存→ToolMessage 链路已走通；写护栏与 deliverable 豁免正交。
- **187 passed**；`python -m bobanana --selfcheck` PASS（15 tools 含 `grep_file`）。

## §5 用户操作

无 env 变更。升级后 Agent 默认大文件 outline + grep 先行；交付报告步仍须 pytest collect 后 write。
