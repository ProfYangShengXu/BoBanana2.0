# 更新日志：report-truth 4（5.30-5 伪代码/页眉/写步顺序）

**版本目标**：2.1.4 (`report-truth-4`)

## 逻辑链

1. `FALSE_CLAIM` + `_collect_pseudocode_violations`：`_build_graph`、路径遍历误报、捏造 `raise ValueError`
2. `_check_agent_header`：强制 `> Agent: BoBanana x.y.z`
3. `registry._write`：`deliverable_path` 下须先 `pytest --collect-only` 才允许 write

## 自查

- P0：FALSE_CLAIM `_build_graph`/路径遍历；`_collect_pseudocode_violations` + prose ValueError 检测
- P1：`_check_agent_header`；`deliverable_write_blocked` + `begin_deliverable_write_step`
- pytest 92 passed；selfcheck PASS
