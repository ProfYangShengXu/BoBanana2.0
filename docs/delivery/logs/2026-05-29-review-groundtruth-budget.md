# 更新日志 — 2026-05-29 · 审查拿真实证据 + 难度/预算去棘轮 + 哨兵不泄漏 + 上下文有界

> **关联任务**：对当前 agent 的严肃批判后的修复。核心结论：审查器只看执行器自述、从不看真实产物 → 「严格审查」名不副实；动态难度是只增不减的棘轮 → 成本蔓延；`REPLAN_NEEDED` 哨兵泄漏进产物/记忆；上下文无预算膨胀；`difficulty` 字段装饰化。
> **状态**：已完成（47 离线用例通过；live e2e 未在本轮重跑，上次会话已通过）

---

## 1. 计划

### 1.1 改动范围
| 路径 | 动作 | 说明 |
|------|------|------|
| `bobanana/agents/executor.py` | 修改 | 执行单步时收集「证据」（write_file 写入路径+内容片段、run_shell 命令+输出片段），暴露 `last_evidence`；返回值仍为字符串总结（不破坏调用方/测试） |
| `bobanana/agents/reviewer.py` | 修改 | `review_artifact(..., evidence)` 接收真实证据；ARTIFACT_SYSTEM 改为「只依据下方真实产物/命令输出评审，自述无证据不得 approve；发现占位/TODO/未跑通必须驳回」 |
| `bobanana/graph.py` | 修改 | ①exec_review 传入 `executor.last_evidence`；②难度真实化：每步有效额外预算 = `max(tool_iter_bonus, round(difficulty*max_tool_iters*0.5))`；③`_advance_node` 重置 `tool_iter_bonus=0`（per-step），`difficulty` 持久作为基线；④`REPLAN_NEEDED` 在重规划预算耗尽时改写为诚实失败文案，不泄漏哨兵 |
| `bobanana/memory/working_memory.py` | 修改 | `add_turn` 单条 turn 截断（上限 ~2000 字符），从源头约束上下文膨胀 |
| `bobanana/memory/manager.py` | 修改 | `recall_conversation` 单条 turn 渲染截断（防超长 turn 进上下文） |
| `tests/test_features.py` | 修改 | 新增：执行器证据收集、审查器收到证据、难度驱动预算+per-step 重置、哨兵不泄漏、turn 截断 |
| `README.md`/`docs/PROJECT.md` | 修改 | 文档：审查基于真实证据、难度语义 |

### 1.2 明确不做
- 不让审查器/门直接持有工具去主动跑测试（保持图简单、可控、可测）；改为「执行器把真实产物/命令输出作为证据上交」，审查器据此判定。后续可再加「验证步骤」。
- 不改 intent 与 graph 的 `is_code_task` 重复判定（第 7 项），避免一次改动过大。

### 1.3 依赖前置
- 无新增依赖。

---

## 2. 目标逻辑链（SSOT）

| 环节 | 预期 | 文件/函数 |
|------|------|-----------|
| 入口 | execute 节点跑 ReAct 工具循环 | `graph._execute_node` → `ExecutorAgent.execute` |
| 输入校验 | 难度→基线预算；retry bonus 叠加；封顶 2×base | `graph._execute_node`（算 extra）+ `executor.execute`（封顶） |
| 核心逻辑 | 执行器边跑边记录证据（写入/命令输出） | `executor.execute` 收集 `last_evidence` |
| 副作用 | 审查器据真实证据评审，而非自述 | `graph._exec_review_node` → `reviewer.review_artifact(evidence=...)` |
| 返回/展示 | 通过→记 result；未通过/预算耗尽→诚实失败、哨兵不入产物 | `graph._advance_node` / `_execute_node`（哨兵改写） |
| 失败与回滚 | 重规划预算在则 replan；否则诚实失败文案；难度/预算逐步自适应且 per-step 重置 | `graph._route_after_execute` / `_advance_node` 重置 bonus |

### 2.2 验收标准
- [x] 既有 40 离线用例仍过；新增用例过（共 47 passed）。
- [x] 执行器跑完一步后 `last_evidence` 含其 write_file 内容片段 / run_shell 输出片段。
- [x] `review_artifact` 收到的 content 中包含证据块。
- [x] 难度高→该步 extra 预算 > 0（不依赖驳回）；`_advance_node` 后 `tool_iter_bonus==0`，`difficulty` 保留。
- [x] 重规划预算耗尽时 `step_output` 不以 `REPLAN_NEEDED` 开头（已改写为诚实失败）。
- [x] 超长 turn 存入后被截断到上限以内。
- [x] `--selfcheck` PASS。

---

## 3. 实施记录
| 时间 | 改动 | 差异 |
|------|------|------|
| 2026-05-29 | executor：`last_evidence` 收集 write/shell 片段，有界截断 | 按计划 |
| 2026-05-29 | reviewer：`review_artifact(evidence=…)` + 证据优先提示词 | 按计划 |
| 2026-05-29 | graph：传证据、难度基线预算、per-step 重置 bonus、哨兵改写 | 按计划 |
| 2026-05-29 | working_memory/manager：turn 截断 | 按计划 |
| 2026-05-29 | tests：+7 离线用例 | 按计划 |

---

## 4. 阶段二自查结论
- [x] 入口/数据流/分支与计划一致：execute 收集证据 → exec_review 传 evidence → advance 重置 bonus；哨兵在预算耗尽时改写。
- [x] 验收满足：`pytest` 47 passed；`--selfcheck` 全 PASS。

**偏差说明**：未在本轮重跑 `pytest -m live`（约 170s/次）；离线 + selfcheck 已覆盖新逻辑。审查器仍不主动跑测试——证据来自 executor 已执行的 write/shell，后续可加独立「验证步骤」节点。
