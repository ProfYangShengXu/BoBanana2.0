# 2026-06-02 — 框架自动拦幻觉（report_validation + blocklist）

## 1. 目标

6.1 运行交付物含 `ToolRegistry`/`FileTools`/假测试文件等幻觉；`read_file` 失败 block 同路径 `write_file`。在框架层自动拦截，不依赖 agent 脚本验证。

## 2. 逻辑链

- 入口：`validate_report_content` / `verify_deliverable_on_disk`（graph `exec_review`、finalize）
- 新增：`FALSE_CLAIM`（6.1 类名/路径）、幻影 `tests/test_*.py`、`:line` 引用校验、计划解析 `deliverable_min_lines` / `deliverable_require_line_refs`
- 副作用：`tool_blocklist` read/write 分 key，read 永久失败不挡 write
- 失败：violations → `report_val_ok=False` → reviewer 不通过

## 3. 改动文件

- `bobanana/report_validation.py`
- `bobanana/tool_blocklist.py`
- `bobanana/graph.py`
- `tests/test_features.py`
- `docs/PROJECT.md`

## 4. 自查结论

- `validate_report_content` 对 6.1 样例报告触发多条 FALSE_CLAIM + 幻影测试（若文中引用）。
- read 失败不再 block 同路径 write；`test_blocklist_read_failure_does_not_block_write` 通过。
- `pytest tests/`：**205 passed**, 2 deselected；`python -m bobanana --selfcheck` PASS。

## 5. 运维

`pytest tests/test_features.py -q -k "validate_report or blocklist"`
`python -m bobanana --selfcheck`
