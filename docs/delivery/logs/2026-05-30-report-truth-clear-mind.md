# 2026-05-30 — report truth + /clear mind

**Release**: BoBanana `2.1.1` (`report-truth`)

## 目标

- `/clear mind` 手动清任务污染记忆
- P0–P2：报告日期/事实校验、交付路径、finalize 诚实、页眉元数据
- 必要时 `web_search` 核验外部论断

## 改动

| 模块 | 变更 |
|------|------|
| `memory/*` | `clear_turns`, `clear_facts_categories`, `clear_mind` |
| `report_validation.py` | 新建：页眉、日期/谬误/路径校验 |
| `plan_validation.py` | 架构≤8步、必填 memory/tests/registry、交付路径 |
| `graph.py` | task_read_paths、exec_review 报告校验、finalize 约束 |
| `registry.py` | 写前禁读 deliverable |
| `tui.py` | `/clear mind` |
| `version.py` | 2.1.1 |

## 自查

- clear_mind 保留 scratch index
- 错误日期 / Chroma 谬误 → validation 不通过
- 架构 write 须在 docs/delivery/output/

## 运维

- pytest + selfcheck
