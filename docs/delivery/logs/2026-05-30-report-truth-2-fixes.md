# 交付日志：report-truth 2.1.2（5.30-3 回归修复）

**版本**：BoBanana 2.1.2 (`report-truth-2`, 2026-05-30)

## 背景

5.30-3 运行暴露五类 report-truth 缺口：plan 交付路径误报、建议新增路径被判 violation、FALSE_CLAIM 过窄、shell `type`/`findstr` 旁路读交付物、step8 审查失败但磁盘 OK 导致 finalize/directive_gate 叙事矛盾。

## 变更摘要

1. **plan_validation**：仅对 `write_file` 步的 `extract_write_path()` 调用 `validate_architecture_deliverable_path`；step1 读 `docs/PROJECT.md` 不再误报。
2. **report_validation**：`_is_proposed_new_path` 跳过「可命名为/建议新增」语境；扩充 `FALSE_CLAIM_PATTERNS`（`run_bobanana`、`list_symbols`、MCP 未集成、`execute_tool` 等）；新增 `verify_deliverable_on_disk` / `deliverable_disk_evidence_block` / `resolve_deliverable_path`。
3. **registry + shell_tools**：`is_shell_reading_file` 拦截 `type`/`cat`/`findstr`/`head`/`tail`/`more` 读交付物。
4. **graph**：`_advance_node` 磁盘 soft-pass；补救步清除 superseded `failed_steps`；`_directive_gate_node` 注入 `DELIVERABLE_ON_DISK`；`_finalize_node` 以磁盘 excerpt 为 ground truth。
5. **executor**：SYSTEM 禁止 shell 读交付物验证。

## 测试

- 新增 9 条回归用例（plan FP、proposed path、false claims、shell block、verify_deliverable_on_disk）。
- `pytest` 全绿；`python -m bobanana --selfcheck` PASS。

## 涉及文件

`plan_validation.py`, `report_validation.py`, `graph.py`, `tools/shell_tools.py`, `tools/registry.py`, `agents/executor.py`, `version.py`, `tests/test_features.py`, `docs/PROJECT.md`.
