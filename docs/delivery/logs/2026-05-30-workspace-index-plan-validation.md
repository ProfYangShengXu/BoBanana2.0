# 2026-05-30 — workspace index + plan validation（路径防打转）

**Release**: BoBanana `2.1.0` (`path-guard`)

## 1. 目标

消除规划/执行阶段猜路径、计划膨胀、shell 摸底、工具目录误读五类打转。

## 2. 计划与逻辑链

```
START → prepare_workspace (index + tool_catalog → scratch)
      → plan (Live index + map 约束)
      → plan_review (validate_plan + reviewer)
      → execute / revise_plan (phantom 强制修订)
```

## 3. 改动文件

| 文件 | 变更 |
|------|------|
| `bobanana/workspace_index.py` | 新建：程序化文件树 |
| `bobanana/plan_validation.py` | 新建：phantom/unknown/步数校验 |
| `bobanana/graph.py` | `prepare_workspace` 节点、validation 路由 |
| `bobanana/workspace_map.py` | scratch 注入 |
| `bobanana/agents/planner.py` | Live index + validation_errors |
| `bobanana/agents/reviewer.py` | PLAN_SYSTEM + validation 块 |
| `bobanana/agents/executor.py` | 禁止 shell 探索 |
| `bobanana/tools/shell_tools.py` | dir/ls 引导 ERROR |
| `bobanana/app.py` / `tui.py` | 架构任务 max_plan_revisions≤1 |
| `bobanana/state.py` | plan_validation 字段 |
| `tests/test_features.py` | 回归测试 |
| `docs/PROJECT.md` | 路径防打转小节 |

## 4. 自查结论

- 入口：`prepare_workspace` 写 scratch，不耗 LLM。
- 校验：`phantom_hits` 强制不通过；架构步数>6 不 ok。
- 执行：shell `dir`/`ls` 返回引导 ERROR，非 TIMEOUT。
- 预算：架构 + task_size≥0.5 时 plan 修订≤1。

## 5. 运维

- `pytest` 离线套件（venv）
- `python -m bobanana --selfcheck`
