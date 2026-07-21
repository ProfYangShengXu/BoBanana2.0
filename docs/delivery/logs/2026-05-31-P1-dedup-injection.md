# 更新日志：P1 方案 — Planner 上下文去重 + 工作记忆按需分级

**日期**: 2026-05-31
**Agent**: BoBanana 2.1.4
**任务**: 实现 Token 优化方案 P1（方案 2 + 方案 4）

---

## 1. 计划

### 方案 2：Planner 上下文去重与差分传递

**问题**: `PlannerAgent.plan()` 在 revision 时，将整个 `prior_plan.model_dump_json(indent=2)` 重新注入 prompt，导致大量重复 Token。

**方案**: 改为只传递差分（diff）—— 即 reviewer 的 suggestions 与 prior_plan 中**实际被修改的部分**。

**改动文件**: `bobanana/agents/planner.py`

**具体实现**:
1. 在 `PlannerAgent.plan()` 中，当 `prior_plan` 和 `review` 都存在时，不再注入完整 `prior_plan.model_dump_json()`，而是注入一个精简的摘要：
   - 只包含 prior_plan 的 `key_directives`（不变的部分）
   - 只包含 reviewer 建议修改的 step 的 id + description
   - 其余步骤只列出 id + 标题（不展开 description/tools）

### 方案 4：工作记忆注入按需分级

**问题**: `MemoryManager.build_context()` 每次构建完整 context，包含所有 working turns + tracked files + facts，即使当前 query 不需要。

**方案**: 根据 query 类型（planning vs execution vs review）分级注入：
- **planning**: 注入 tracked files + facts + session summary（不注入 working turns）
- **execution**: 注入 working turns（最近 4 条）+ tracked files（不注入 facts）
- **review**: 注入 working turns（最近 2 条）+ session summary（不注入 tracked files）

**改动文件**: `bobanana/memory/manager.py`

---

## 2. 逻辑链

```
PlannerAgent.plan() 调用
  → 检查 prior_plan 和 review 是否存在
  → 若存在，调用 _summarize_plan_diff() 生成精简摘要
  → 将摘要注入 prompt（而非完整 plan JSON）
  → Token 节省：~60-80% 的 plan 相关 Token

MemoryManager.build_context() 调用
  → 检查 caller 传入的 context_type 参数
  → 根据 context_type 选择性注入各 memory 组件
  → Token 节省：~40-60% 的 memory 相关 Token
```

---

## 3. 改动清单

| 文件 | 改动 |
|------|------|
| `bobanana/agents/planner.py` | 新增 `_summarize_plan_diff()` 方法；修改 `plan()` 中 prior_plan 注入逻辑 |
| `bobanana/memory/manager.py` | 修改 `build_context()` 签名，新增 `context_type` 参数；实现分级注入 |

---

## 4. 自查结论

（阶段二填写）

---

## 5. RUNBOOK

（阶段三填写）
