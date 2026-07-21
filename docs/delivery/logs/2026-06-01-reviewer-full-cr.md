# 审查员全文 Code Review P0-P2

## §1 计划

P0 step touch + 小文件全文 DISK_REVIEW | P1 diff/outline | P2 ast/TODO 门禁 + config

## §2 逻辑链

execute → begin_step_review → write/edit 记 before → exec_review → build_review_snapshot → deterministic → reviewer

## §3 实施记录

- 新增 `bobanana/review_snapshot.py`：`StepTouch`、`build_review_snapshot`、`run_deterministic_checks`
- `Toolbox` 增加步级状态：`begin_step_review()`、`step_touches`、`step_before`
- `registry._write/_edit` 成功后记录本步 touched path + before 内容
- `graph._execute_node` 每步执行前重置 step review 状态
- `graph._exec_review_node` 接入 `DISK_REVIEW` + code deterministic 报告
- `reviewer.review_artifact` 扩展参数：`disk_review` / `deterministic_report` / `deterministic_ok`
- `config/.env.example` 增加 `BOBANANA_REVIEW_*` 5 项配置
- 测试：`tests/test_features.py` 新增 reviewer-full-cr 相关 9 项（P0/P1/P2）
- 文档：`docs/PROJECT.md` 更新变更索引与「审查员全文 Code Review」说明

## §4 自查结论

- 逻辑链路已完整打通：execute 前清步级状态 → write/edit 记录 before+touch → exec_review 读盘快照 → deterministic（语法/占位）→ reviewer verdict。
- 大文件策略生效：`edit` 优先 unified diff，`write` 优先 outline，多文件场景有优先级降级。
- 回退开关可用：`BOBANANA_REVIEW_ENABLE=0` 时 snapshot 与 deterministic 均关闭，行为回退到旧 evidence-only。
- 测试与运维：
  - `pytest tests/test_features.py -q -k "review_snapshot or step_touch or disk_review or deterministic_syntax or review_disabled or review_artifact"`：9 passed
  - `pytest tests/ --ignore=tests/test_e2e_live.py -q`：197 passed
  - `python -m bobanana --selfcheck`：PASS（settings/sessions/memory/skills/mcp/tools/graph）
