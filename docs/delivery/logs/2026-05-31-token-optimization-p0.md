# 更新日志 — 2026-05-31 · Token 优化 P0 方案实施

> **关联任务**：根据 Token 优化方案报告实施 P0 方案（Executor 消息历史摘要截断 + Token 统计增强与预算控制）
> **状态**：已交付
> **本文件用途**：写代码**之前**锁定计划与目标逻辑链；阶段二自查时**逐条对照**此文件，不得偏离却不更新本文。

---

## 1. 本次计划更新的内容

### 1.1 目标（完成后用户能做什么）

- Executor 的 `execute()` 方法在 ReAct 循环中自动截断消息历史，避免无限膨胀导致 Token 浪费
- Token 统计模块支持迭代级统计、消息长度监控和预算告警
- 所有优化不影响现有功能逻辑，测试全部通过

### 1.2 计划改动范围（文件 / 模块）

| 路径 / 模块 | 计划动作 | 说明 |
|-------------|----------|------|
| `bobanana/agents/executor.py` | 修改 | 在 ReAct 循环中添加消息历史摘要截断逻辑 |
| `bobanana/telemetry/tokens.py` | 修改 | 添加迭代级统计、消息长度监控、预算告警 |
| `tests/test_tokens.py` | 新增 | Token 统计模块的单元测试 |

### 1.3 不在本次范围（明确不做）

- 不修改 Planner、MicroPlanner、WorkingMemory 等模块（P1/P2 方案后续实施）
- 不修改 graph.py 中的编排逻辑
- 不修改 state.py 中的状态定义
- 不涉及 Token 计费或持久化存储

### 1.4 依赖与前置条件

- 无外部依赖变更
- 现有测试套件必须全部通过

---

## 2. 目标逻辑链（阶段二对照 SSOT）

### 2.1 链路详述

#### P0 方案 1：Executor 消息历史摘要截断

| 环节 | 预期行为 | 关键文件/函数（计划） |
|------|----------|------------------------|
| 触发入口 | `ExecutorAgent.execute()` 的 ReAct 循环中，每次迭代后检查消息列表大小 | `executor.py:ExecutorAgent.execute()` |
| 输入校验 | 检查 `messages` 列表长度 > `MAX_HISTORY`（默认 12）且非 SystemMessage | `executor.py:_should_summarise()` |
| 核心逻辑 | 将早期 HumanMessage + AI 对压缩为一条摘要 SystemMessage，保留最近的 N 条消息 | `executor.py:_summarise_history()` |
| 持久化/副作用 | 无持久化；摘要消息替换原消息列表中的早期条目 | 无 |
| 返回/展示 | 不影响最终返回值；摘要仅减少发送给 LLM 的 Token | 无 |
| 失败与回滚 | 摘要失败时（如 JSON 序列化错误）回退到简单截断：只保留最后 N 条消息 | `executor.py:_summarise_history()` 异常处理 |

#### P0 方案 5：Token 统计增强与预算控制

| 环节 | 预期行为 | 关键文件/函数（计划） |
|------|----------|------------------------|
| 触发入口 | `TokenUsageHandler.on_llm_end()` 每次 LLM 调用后触发 | `tokens.py:TokenUsageHandler.on_llm_end()` |
| 输入校验 | 检查 response 中是否有 token_usage 或 usage_metadata | 现有逻辑 |
| 核心逻辑 | 新增 `MessageLengthMonitor` 类：记录每次消息的字符长度和 Token 估算；新增 `BudgetController` 类：设置预算阈值并在超限时触发告警回调 | `tokens.py:MessageLengthMonitor`, `tokens.py:BudgetController` |
| 持久化/副作用 | 统计信息存储在内存中，不持久化 | 无 |
| 返回/展示 | `MessageLengthMonitor.report()` 返回统计摘要；`BudgetController.check()` 返回是否超限 | 无 |
| 失败与回滚 | 统计失败时静默忽略，不影响主流程 | try/except 包裹 |

### 2.2 验收标准（可观测）

- [x] `executor.py` 中新增 `_should_summarise()` 和 `_summarise_history()` 方法，在消息超过阈值时自动截断
- [x] `tokens.py` 中新增 `MessageLengthMonitor` 类，支持逐次记录和报告
- [x] `tokens.py` 中新增 `BudgetController` 类，支持预算阈值和告警回调
- [x] pytest 测试套件全部通过（collect-only + 实际运行）
- [x] 无 TODO/占位符/调试打印残留

### 2.3 风险与边界

| 场景 | 预期处理 |
|------|----------|
| 消息列表为空或只有 SystemMessage | `_should_summarise()` 返回 False，不截断 |
| 摘要生成失败（JSON 异常） | 回退到简单截断：保留最后 N 条消息 |
| Token 统计回调异常 | try/except 包裹，静默忽略 |
| 预算阈值设为 0 或负数 | `BudgetController.__init__` 中 clamp 到 0 |

---

## 3. 实施记录（写代码过程中可追加）

| 时间 | 实际改动 | 与计划差异 |
|------|----------|------------|
| 2026-05-31 | 修改 `executor.py`：添加消息历史摘要截断逻辑 | 函数名使用英式拼写 `summarise` 而非计划中的美式 `summarize`，功能一致 |
| 2026-05-31 | 修改 `tokens.py`：添加 MessageLengthMonitor 和 BudgetController | 无 |
| 2026-05-31 | 新增 `tests/test_tokens.py`：28 个单元测试 | 无 |

---

## 4. 阶段二自查结论（交付前填写）

> 对照第 2 节逐环打勾；有偏差须先更新第 3 节说明，再改代码或修订计划。

- [x] 入口与计划一致
- [x] 数据流与计划一致
- [x] 分支与失败路径与计划一致
- [x] 验收标准已满足（含测试/构建证据）

**偏差说明**：函数名使用英式拼写 `_should_summarise` / `_summarise_history`（计划中写的是美式 `_should_summarize` / `_summarize_history`），已在第 3 节记录。功能完全一致，不影响正确性。

---

## 5. 接线修正（2026-05-31 晚，复核后补交）

> 复核发现：方案 5（Token 统计/预算）当时**只建未接**——`app.py` 用无参 `TokenUsageTracker()` 创建，无预算、无告警回调、`monitor.report()` 无出口、`check_message_length` 无调用方，运行中零可观测效果。本节修正。

| 文件 | 变更 |
|------|------|
| `config.py` / `.env.example` | 新增 `token_budget_total`（env `BOBANANA_TOKEN_BUDGET_TOTAL`，0=关闭） |
| `app.py` | `TokenUsageTracker(budgets=..., on_budget_alert=self._on_token_budget_alert)`；告警回调走 `log.warning`（线程安全，经日志桥进 TUI） |
| `tui.py` | `/memory` 新增 "Token usage" 面板，输出 `monitor.report()` + `budget.report()` |
| `telemetry/tokens.py` | 删除死方法 `check_message_length`（无调用方、无测试） |

接线后可观测效果：配置预算后超限会在日志/TUI 告警一次；`/memory` 随时可见迭代级 token 统计与预算占比。

**新增测试**：`test_alert_callback_fires_on_breach`、`test_app_wires_token_budget`、`test_app_no_budget_when_disabled`。

## 6. 防复发：提示词禁止"空接"

在两处提示词加入硬规则，从源头阻止 agent 再产出休眠基础设施：

- `agents/executor.py` SYSTEM：**No dead wiring (禁止空接)** —— 新符号必须在同一步接到真实调用方，接不通就不写。
- `graph.py` 交付门 directive：同义中文规则，对所有代码任务生效。

验证：166 passed；`--selfcheck` 全 PASS；静态检查 clean。

---

## 7. Bug 修复：摘要截断产生孤儿 tool 消息导致 400 崩溃（5.31-3 runtime 证据）

**现象**：任务运行中 `message history summarised: 16 -> 9 messages` 后立即崩溃：
`BadRequestError 400 - "Messages with role 'tool' must be a response to a preceding message with 'tool_calls'"`。

**根因**：P0 方案1 的 `_summarise_history` 保留"最近 N 条"时，切口可能落在 `AIMessage(tool_calls)` 与其 `ToolMessage` 之间——带 tool_calls 的 AI 消息被摘要掉，对应 tool 结果留在尾部成为孤儿，OpenAI 拒绝。主路径与异常兜底路径都有此缺陷。

**修复**（`agents/executor.py`）：
- 主路径：切口 `split` 向前推过 ToolMessage（`while others[split] is ToolMessage: split += 1`），保证保留尾部不以 tool 消息开头，孤儿 tool 进入摘要。
- 兜底路径：丢弃尾部开头的孤儿 ToolMessage。

**测试**：新增 `test_summarise_never_orphans_leading_tool_message`、`test_summarise_keeps_tool_call_pairing_valid`（重放交替 AI(tool_calls)/Tool 流并校验 API 合法性）；改写原 `test_summarise_with_keep_2`（其断言固化了旧的孤儿行为）。167 passed；`--selfcheck` 全 PASS。

---

## 8. 隐患修复：读取策略与 plan/review 策略矛盾导致空转

**现象（5.31-3）**：用户任务引用 `docs/delivery/output/...md` 作为依据；planner 生成"读取该 .md"步骤，但 `read_file` 对交付输出 .md 有硬拦截（report_validation:202），reviewer 又因"缺少读取证据"反复打回 → 模型空转重读缓存文件，直到触发摘要崩溃。三处策略互相打架。

**修复（让三处一致地尊重拦截）**：

| 文件 | 变更 |
|------|------|
| `agents/planner.py` | SYSTEM 加规则：禁止规划 `read_file docs/delivery/output/*.md`，从请求文本 + 源码/测试推导需求 |
| `plan_validation.py` | 新增 `_reads_blocked_delivery_md`：步骤若"读取"交付输出 .md（写入除外）→ warning + ok=False，plan_review 据此打回，让 planner 早改 |
| `agents/reviewer.py` | ARTIFACT_SYSTEM 加规则：绝不要求读取交付输出 .md，被拒是预期，按实际读到的源码/测试评判 |

**测试**：新增 `test_validate_plan_flags_reading_delivery_output_md`（读→拒、写→放行）。168 passed；`--selfcheck` 全 PASS；lint clean。

**未做**：未放宽拦截本身（仍禁止把未经核实的旧报告当源码/真值）。若希望"用户显式引用的报告可读"，是另一项有风险的策略放宽，留待单独决策。

---

## 9. 规划环节硬性预判 bug

**目的**：让 agent 在 plan 阶段就强制考虑可能的 bug/失败路径，而非只规划 happy path。

| 文件 | 变更 |
|------|------|
| `agents/planner.py` | SYSTEM 新增 **Anticipate bugs at plan time (HARD)**：必须显式推演失败模式（空/None、错误/回滚路径、边界、被改动回归的调用方、并发/取消/半写、Windows 路径/编码/ANSI/CRLF、兼容性），且计划须含 ≥1 个具体校验步骤 +1 条"校验已通过"的 key_directive |
| `agents/reviewer.py` | PLAN_SYSTEM 加第 5 条：计划若只有 happy path / 无校验步骤 → 不批准，强制要求补 |

纯提示词改动，无逻辑/数据结构变更。import ok；168 passed；`--selfcheck` 全 PASS；lint clean。
