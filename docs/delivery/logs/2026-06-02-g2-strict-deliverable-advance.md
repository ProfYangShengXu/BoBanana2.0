# 2026-06-02 — G2 strict_deliverable_advance

## 改动

- `Settings.strict_deliverable_advance` / `BOBANANA_STRICT_DELIVERABLE_ADVANCE`（默认 True）
- `_exec_review_node`：报告步用 `validation_strict_ok` 否决（含 needs_web）
- `_advance_node`：删除报告步 soft-pass；须 review 通过且磁盘 `validation_strict_ok`
- `[补救/*]` 步仍用 `validation_acceptable_ok` 清理 failed_steps（directive 路径）

## 验证

`pytest tests/` — `test_advance_report_strict_*`、`test_exec_review_strict_*`
