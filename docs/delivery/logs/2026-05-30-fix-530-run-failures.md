# 更新日志 — 2026-05-30 · 修复 5.30 运行日志暴露的致命 bug

> **状态**：已完成（57 离线用例通过）

## 根因与修复
| # | 5.30 现象 | 根因 | 修复 |
|---|-----------|------|------|
| 1 | `read_file` 后 `REPLAN_NEEDED: [cached]` 或 docstring | 源码含 `ERROR: TIMEOUT` 字面量被误判 | 仅 `run_shell` 且以 `ERROR: TIMEOUT` 开头才 replan |
| 2 | 反复 `[cached]` → 预算耗尽 | 缓存探索一律 non-productive | 有实质内容的 cached read/list 算 productive |
| 3 | 分析步 EVIDENCE 空 → score=0 | evidence 只收 write/shell | `read_file` 进 evidence |
| 4 | 找 `src/`、`plan_executor.py` | 无 workspace map | `workspace_map.py` 注入 planner/executor |
| 5 | 扫 `.bobanana/tools` 当注册表 | 未用内省工具 | 指引 `describe_tool_registry` + `docs/PROJECT.md` |

## 改动文件
`executor.py` · `workspace_map.py` · `graph.py` · `planner.py` · `reviewer.py` · `tests/test_features.py`
