# 2026-06-02 — G1 计划硬门 strict_plan_gate

## 改动

- `Settings.strict_plan_gate`（`BOBANANA_STRICT_PLAN_GATE`，默认 True）
- `_route_after_plan_review`：`ok=False` 仅 `revise_plan`；修订耗尽 → `plan_exhausted` → `finalize`（partial）
- `_plan_review_node`：strict 且 validation 失败时跳过 LLM `review_plan`
- TUI：`plan_exhausted` 事件面板

## 验证

`pytest tests/` 214 passed；`test_strict_plan_gate_*` ×3
