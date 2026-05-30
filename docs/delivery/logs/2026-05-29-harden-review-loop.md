# 更新日志 — 2026-05-29 · harden-review-loop

> **关联任务**：(1) 修硬审查闭环——所有门禁在异常/预算耗尽时改为「保守阻断 + 如实上报」而非默默放行，步骤级审查未过不再伪装成功；(2) 在不降低审查标准的前提下提升主 agent 通过率——让重试真正有效（结构化修复指令、区分预算耗尽、禁止重复失败探索）+ 校准默认预算。
> **背景**：见严肃批判与 `docs/delivery/output/5,29.md`——审查连续 0 分仍 advance、gate fallback 放行、重试不换策略空转超时。
> **状态**：已完成（28 tests + selfcheck PASS）

---

## 1. 计划

### 1.1 目标
- [ ] 步骤级：exec_review 未通过且预算耗尽 → 该步**如实标记失败**并计入 `failed_steps`，不再当成功 advance。
- [ ] 任务级：DirectiveGate 产不出结构化结论 → fallback 改为 `all_satisfied=False`（保守），不再默认放行。
- [ ] finalize：依据 `failed_steps` + 未满足 directives 计算 `status`（completed/partial），summary **如实陈述**遗留与失败项；final 事件带 status。
- [ ] 提升通过率：executor 重试构造**结构化修复指令**——区分「预算耗尽未完成」vs「质量不足」，逐条编号 suggestions，明令禁止重复已失败的探索。
- [ ] 校准 `max_tool_iters` 默认 8→12（实战证据）。

### 1.2 改动范围
| 路径 | 动作 | 说明 |
|------|------|------|
| `bobanana/state.py` | 修改 | `failed_steps`、`status`；new_state 初始化 |
| `bobanana/graph.py` | 修改 | advance 如实标记失败；finalize 计算 status+上报；final 事件带 status |
| `bobanana/agents/directive_gate.py` | 修改 | fallback 改保守(all_satisfied=False) |
| `bobanana/agents/executor.py` | 修改 | 结构化修复指令（预算耗尽 vs 质量；禁止重复失败探索） |
| `bobanana/config.py`+`.env.example` | 修改 | max_tool_iters 默认 12 |
| `bobanana/tui.py` | 修改 | final 面板按 status 着色；标注失败/未满足 |
| `tests/test_features.py` | 修改 | gate 保守 fallback、失败步骤上报、重试指令、status |
| `README.md`/`docs/PROJECT.md` | 修改 | 文档 |

### 1.3 不在本次范围
- 不重写向量记忆/符号层（批判点 2，单独处理）。
- 不引入总 token 预算闸门（后续）。
- 不改 shell 白名单组合命令漏洞（后续安全专项）。

---

## 2. 目标逻辑链（SSOT）

| 环节 | 预期行为 | 关键文件/函数 |
|------|----------|----------------|
| 步骤执行 | executor 跑 ReAct；重试时收到结构化修复指令 | `executor.execute` |
| 步骤审查 | reviewer 评估；未过 fallback=approved False（保留） | `reviewer._invoke_review` |
| 预算耗尽路由 | 未过且 exec_revisions≥max → advance（防死循环），但 advance 如实标失败 | `_route_after_exec_review`, `_advance_node` |
| 任务级门 | directive_gate 判定；fallback 改 all_satisfied=False | `directive_gate.check` |
| 结束 | finalize 据 failed_steps+unmet 计算 status；done=True 但 status 真实 | `_finalize_node` |
| 展示 | final 面板成功=洋红/部分=黄并列出失败与未满足项 | `tui._render` |
| 失败回滚 | 不死循环（受 max_* 约束）；不确定时阻断方向+上报，绝不静默成功 | graph 路由 |

### 2.2 验收标准
- [ ] 全模块 import；`--selfcheck` 全 PASS；既有 `test_graph_offline` 仍过（向后兼容）。
- [ ] 离线测试：审查未过且预算耗尽 → final status=partial 且 summary 含失败步骤；gate fallback=未满足；重试指令在预算耗尽/质量两种情形文本不同。
- [ ] 默认 max_tool_iters=12。

### 2.3 风险与边界
| 场景 | 处理 |
|------|------|
| 审查永不通过 | max_exec_revisions 限制；advance 标失败而非循环 |
| gate LLM 持续失败 | fallback 不触发 loop（unmet 空），直接 partial 上报，不浪费重试 |
| status 误判 | 仅当有 failed_steps 或 all_satisfied=False 才 partial，保守 |
| 旧序列化无新字段 | 默认值（[]/completed） |

---

## 3. 实施记录
| 时间 | 改动 | 差异 |
|------|------|------|
| 2026-05-29 | state | `failed_steps: List[dict]`、`status: str`；new_state 初始化 [] / "completed" |
| 2026-05-29 | directive_gate | fallback 由 `all_satisfied=True` 改为 `False`（unmet 留空避免空转重试） |
| 2026-05-29 | graph._advance_node | 读 exec_review；未 approved 则该步 result 加 `[未通过审查]` 前缀并入 failed_steps，warning 日志 |
| 2026-05-29 | graph._finalize_node | 据 failed_steps/unmet/gate_unverified 计算 status；partial 时换 HONEST system 提示并列出问题；final 事件带 status |
| 2026-05-29 | executor | 重试指令区分「预算耗尽（Step stopped）→直奔核心动作」与「质量驳回→编号 checklist + 禁止重复失败/缓存调用」 |
| 2026-05-29 | config/.env | max_tool_iters 默认 8→12 |
| 2026-05-29 | tui | final 面板按 status 着色（completed=洋红 / partial=黄并标注 unresolved） |
| 2026-05-29 | tests | +gate 保守 fallback、+重试指令两情形、+审查永不过→partial 上报 |

---

## 4. 阶段二自查结论
- [x] 入口/数据流/分支与计划一致：plan→execute→exec_review→(revise|advance)→directive_gate→finalize；advance 与 finalize 现在如实承载失败/未验证语义。
- [x] 验收满足：`pytest -q` 28 passed；`--selfcheck` 全 PASS；`test_graph_offline` 向后兼容通过；新增 3 项断言覆盖保守 fallback / status=partial / 重试指令分支。

**偏差说明**：无功能性偏差。`done` 字段仍保留 `True`（表示流程结束），任务成败由新增 `status` 字段表达，避免破坏既有调用方对 `done` 的依赖。
