# 2026-06-02 — G4 architecture directive caps

## 改动

- `plan_validation.is_architecture_task`（公开）、`architecture_plan_step_cap`
- `Settings.architecture_max_remedial_steps` / `BOBANANA_ARCHITECTURE_MAX_REMEDIAL_STEPS`（默认 2）
- `_directive_gate_node`：架构任务禁用 `continue_next_round`；`[补救/*]` 每轮最多 N 步、总长 ≤ min(8+N, 10)
- 触顶写入 `failed_steps`，`directive_loop=False`

## 验证

`pytest tests/` — `test_directive_gate_architecture_*`、`test_split_remedial_*`
