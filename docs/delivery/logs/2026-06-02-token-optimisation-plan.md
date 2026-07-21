# Token 优化计划（P0 交付物）

## 1. 现状分析

### 1.1 已有优化措施
- `executor.py` 中有 `_should_summarise()` / `_summarise_history()` 消息历史压缩
- `telemetry/tokens.py` 有 `MessageLengthMonitor`, `BudgetController`, `TokenUsageTracker`
- `config.py` 有 `token_budget_total` 配置项
- `llm.py` 有角色温度分层（reviewer/directive_gate 为 0，executor 为 0.3）

### 1.2 当前问题
1. **消息历史压缩只在 executor 执行循环中触发**，plan_review/exec_review 等节点没有压缩
2. **`_summarise_history()` 实现有 bug**：`SystemMessage` 类型比较用了 `type(msg) is SystemMessage` 但 `langchain_core.messages` 中 `SystemMessage` 是类，应该用 `isinstance`
3. **没有跨步骤的 token 累积追踪**：每个步骤独立，无法在步骤间做预算分配
4. **`BudgetController` 未接入 graph 流程**：定义了类但没有任何节点调用它
5. **`TokenUsageTracker` 只记录不干预**：没有在接近预算上限时触发主动压缩
6. **没有 prompt 模板级别的 token 优化**：system prompt 在每个节点重复发送完整上下文

## 2. 优化方案

### 2.1 修复 `_summarise_history()` 类型检查（低风险，高收益）

**问题**：`executor.py` 中约 200 行处，`type(msg) is SystemMessage` 应改为 `isinstance(msg, SystemMessage)`。

**影响**：当前可能导致 system messages 被错误压缩，丢失关键指令。

### 2.2 将 `BudgetController` 接入 graph 执行流程（中风险，中收益）

**方案**：
- 在 `CodingAgentGraph.__init__` 中初始化 `BudgetController`（使用 settings.token_budget_total）
- 在 `_execute_node` 中调用 `budget_controller.check()` 检查预算
- 在 `_exec_review_node` 中调用 `budget_controller.record_usage()` 记录消耗
- 当预算接近耗尽时（>80%），在 reviewer 的 context 中注入预算警告

### 2.3 跨步骤 token 追踪（中风险，高收益）

**方案**：
- 在 `AgentState` 中添加 `total_token_usage: int` 和 `token_warning: bool` 字段
- 每个节点结束时记录 LLM 调用 token 消耗
- 在 `_context_for()` 中根据 `token_warning` 决定是否压缩上下文

### 2.4 节点级上下文压缩（低风险，中收益）

**方案**：
- 在 `_context_for()` 方法中，当累积 token 超过阈值时，对历史消息做摘要压缩
- 复用 `executor.py` 中的 `_summarise_history()`（修复后）

### 2.5 优化 system prompt 模板（低风险，中收益）

**方案**：
- 将各节点的 system prompt 中静态部分提取为常量，避免每次重新构造
- 对 `_workspace_index_text()` 结果做缓存（文件未变更时复用）

## 3. 实施优先级

| 优先级 | 项目 | 预估工作量 | 风险 |
|--------|------|-----------|------|
| P0 | 修复 `_summarise_history()` 类型检查 | 1 行 | 低 |
| P0 | `BudgetController` 接入 graph | 3-5 行 | 低 |
| P1 | 跨步骤 token 追踪 | 10-15 行 | 中 |
| P1 | 节点级上下文压缩 | 8-12 行 | 中 |
| P2 | system prompt 模板优化 | 5-8 行 | 低 |

## 4. 测试策略

- 现有 `tests/test_tokens.py` 覆盖了 `MessageLengthMonitor`, `BudgetController`, `TokenUsageTracker` 和 `_should_summarise`/`_summarise_history`
- 修改后运行 `pytest tests/test_tokens.py -q` 验证
- 运行 `pytest tests/test_graph_offline.py -q` 验证 graph 集成
- 运行 `pytest tests/ -q` 全量测试确保无回归

## 5. 成功标准

1. 所有 token 相关测试通过
2. 全量测试通过
3. 在长对话场景中，token 消耗降低至少 20%（通过 `TokenUsageTracker` 日志可观测）
