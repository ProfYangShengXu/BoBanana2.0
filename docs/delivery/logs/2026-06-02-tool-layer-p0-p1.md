# 2026-06-02 — 工具层优化 P0 剩余 + P1

## 1. 目标

落实 [2026-06-02-tool-layer-optimization.md](../output/2026-06-02-tool-layer-optimization.md) 第 8 节 P0-3/P0-4 与 P1 项。

## 2. 逻辑链

- P0-3：`check_tool_blocked` → `deliverable_block_hint` → executor 追加 Hint
- P0-4：`set_deliverable_requirements` → `format_deliverable_requirements` → graph `extra_ctx`
- P1-1：`_grep` 查 `_grep_recent` 短路重复
- P1-2：`_read_outline` 页脚 grep hint
- P1-3：`step_start` event + TUI 展示 pytest collect

## 3. 改动文件

- `bobanana/report_validation.py` — `deliverable_block_hint`, `format_deliverable_requirements`
- `bobanana/agents/executor.py` — block hint 追加
- `bobanana/graph.py` — extra_ctx, step_start pytest_collect_count
- `bobanana/tools/registry.py` — grep dedup
- `bobanana/tools/file_tools.py` — outline hint
- `bobanana/tui.py` — pytest collect 展示
- `tests/test_features.py` — +6 单测

## 4. 自查结论

- 交付物 block 时 tool result 含 `Hint (deliverable)`；重复 grep 返回 duplicate 错误且不 invoke rg。
- outline 大文件输出含 `Hint: grep_file`。
- `pytest tests/`：**211 passed**, 2 deselected；`python -m bobanana --selfcheck` PASS。

## 5. 运维

```bash
pytest tests/test_features.py -q -k "deliverable or grep_duplicate or outline or step_start"
pytest tests/ -q
python -m bobanana --selfcheck
```
