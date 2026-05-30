# 更新日志 — 2026-05-29 · directives-and-exploration-cache

> **关联任务**：(1) 每个规划回合由主 LLM 设定「重要指令(key_directives)」，未全部完成不结束；(2) 探索结果(read_file/list_dir/只读 shell)存入结构化记忆，命中即返回、不重复调用探索工具。
> **背景**：见 `docs/delivery/output/5,29.md` 分析——Executor 探索读盘耗尽工具预算、重试不换策略、审查不通过仍 advance。本次从「目标达成门」+「探索去重」两个机制层面治理。
> **状态**：实施中

---

## 1. 计划

### 1.1 目标
- [ ] Planner 每次产出/修订计划时附带 `key_directives`（任务级硬性验收，可验证）。
- [ ] 所有步骤跑完后增设「指令门」：用结构化判定每条 directive 是否满足；未满足且预算未尽 → 追加补救步骤回到 execute；否则 finalize 并在总结标注未满足项。
- [ ] 探索类工具结果落结构化记忆缓存；相同 (工具+参数) 再次调用直接命中返回，并提示勿重复；命中不消耗工具预算。
- [ ] 发生写副作用(write_file / 非只读 shell)后使探索缓存失效，保证后续探索拿到最新状态。

### 1.2 计划改动范围
| 路径 | 动作 | 说明 |
|------|------|------|
| `bobanana/state.py` | 修改 | `Plan.key_directives`；新增 `DirectiveCheck`；`AgentState.directive_revisions` |
| `bobanana/agents/planner.py` | 修改 | prompt 要求产出 key_directives |
| `bobanana/agents/executor.py` | 修改 | 注入 key_directives；`[cached]` 命中视为非生产(不耗预算) |
| `bobanana/agents/directive_gate.py` | 新增 | DirectiveGate：结构化判定 directives 是否全部满足 |
| `bobanana/graph.py` | 修改 | execute 传 directives；新增 directive_gate 节点与路由；finalize 标注未满足 |
| `bobanana/memory/structured_memory.py` | 修改 | `exploration` 表 + get/save/clear |
| `bobanana/memory/manager.py` | 修改 | recall/record/clear_exploration 门面 |
| `bobanana/tools/registry.py` | 修改 | read_file/list_dir/只读 shell 缓存；写副作用清缓存 |
| `bobanana/config.py` + `.env.example` | 修改 | `max_directive_revisions`、`enable_exploration_cache` |
| `tests/test_features.py` | 修改 | directive gate、exploration cache、cached 非生产 |
| `README.md` / `docs/PROJECT.md` | 修改 | 文档 |

### 1.3 不在本次范围
- 不改变三层记忆既有路由；探索缓存是结构化层的新增表，独立。
- 不缓存写类 shell；只读 shell 命中后遇写副作用即失效（保守正确优先于命中率）。
- directive 判定失败回退为「放行 + 标注」，不无限循环。

---

## 2. 目标逻辑链（SSOT）

| 环节 | 预期行为 | 关键文件/函数 |
|------|----------|----------------|
| 规划入口 | planner 产出 Plan(含 key_directives) | `planner.plan` |
| 执行 | executor 每步系统提示注入 key_directives，强调「步骤完成≠任务完成」 | `executor.execute` |
| 探索去重 | read_file/list_dir/只读 shell 先查缓存，命中加 `[cached]` 前缀返回；未命中执行后写缓存 | `registry._read/_list/_run_shell` |
| 缓存失效 | write_file/非只读 shell 成功 → `clear_exploration()` | `registry._write/_run_shell` |
| 预算保护 | `[cached]`/ERROR/Step stopped 命中算非生产，不耗 max_tool_iters | `executor._is_nonproductive` |
| 指令门 | 全步骤完成后 directive_gate 判定；未满足且 `directive_revisions<上限` → 追加步骤回 execute | `graph._directive_gate_node/_route_after_gate` |
| 结束 | 全满足或预算尽 → finalize；未满足项写入 summary | `graph._finalize_node` |
| 失败回滚 | directive LLM 异常/空 directives → 直接放行 finalize | `directive_gate`, gate 节点 |

### 2.2 验收标准
- [ ] 全模块 import；`--selfcheck` 全 PASS。
- [ ] 离线测试：空 directives 时 gate 直接放行（向后兼容 test_graph_offline）；exploration 命中返回缓存且 write 后失效；`[cached]` 判为非生产。
- [ ] graph 装配含 directive_gate 节点。

### 2.3 风险与边界
| 场景 | 处理 |
|------|------|
| 文件被外部改动后读到旧缓存 | 写副作用清缓存；只读 shell 命中后遇写即失效；缓存仅本进程 SQLite |
| directive 判定死循环 | `max_directive_revisions` 上限，超出即放行并标注 |
| 旧 Plan 序列化无 key_directives | 字段默认空列表，gate 空则放行 |
| 缓存命中却仍需最新 | 提示模型「如已变更先执行写操作」；写后自动失效 |

---

## 3. 实施记录
| 时间 | 改动 | 差异 |
|------|------|------|
| 2026-05-29 | `state.py`：`Plan.key_directives`、`DirectiveCheck`、`directive_revisions/check/loop` | + |
| 2026-05-29 | `structured_memory.py`：`exploration` 表 + get/save/clear_exploration | + |
| 2026-05-29 | `manager.py`：recall/record/invalidate_exploration 门面 | + |
| 2026-05-29 | `registry.py`：read_file/list_dir/只读 shell 读缓存；write/写 shell 清缓存；`[cached]` 前缀 | + |
| 2026-05-29 | `planner.py`：prompt 要求产出 2-5 条可验证 key_directives | + |
| 2026-05-29 | `agents/directive_gate.py`：DirectiveGate（结构化判定 + 容错回退） | + |
| 2026-05-29 | `executor.py`：注入 key_directives；`[cached]` 计为非生产（不耗预算） | + |
| 2026-05-29 | `graph.py`：execute 传 directives；directive_gate 节点+路由；finalize 标注未满足；recursion_limit 提升 | + |
| 2026-05-29 | `config.py`+`.env.example`：`max_directive_revisions`、`enable_exploration_cache` | + |
| 2026-05-29 | `tui.py`：渲染 directive_gate 事件 | + |
| 2026-05-29 | `tests/test_features.py`：缓存命中/失效/禁用、cached 非生产、gate 空放行/报告未满足/端到端循环 | + |

---

## 4. 阶段二自查结论
- [x] 入口/数据流/分支与计划一致：
  - 规划 → planner 产出含 key_directives 的 Plan；执行每步注入 directives。
  - 探索 read_file/list_dir/只读 shell 先查 SQLite 缓存，命中加 `[cached]` 返回且不耗预算；write/写类 shell 成功后 `clear_exploration()` 失效。
  - 全步骤完成 → directive_gate 结构化判定；未满足且 `directive_revisions<上限` → 追加「[补救]」步骤、loop=True 回 execute；否则 finalize（summary 标注未满足项）。
- [x] 失败/回滚：空 directives 或 gate 无法产出结构化结论 → 放行 finalize，不死循环；缓存仅缓存非 ERROR/非空结果。
- [x] 验收证据：
  - `pytest -q` → **25 passed**（新增 7 项：缓存命中/失效/禁用、`[cached]` 非生产、gate 空放行/报告未满足/端到端 unmet→loop→finish）。
  - 既有 `test_graph_offline`（无 key_directives）仍通过 → 向后兼容（gate 空直接放行）。
  - `--selfcheck` 全 PASS，graph 编译含 directive_gate 节点。
  - lint：IDE 诊断 0 错误；`compileall` 历史已验证。

**偏差说明**：
- 写副作用采用「整表失效」的保守策略（而非按路径精确失效），命中率略降但保证探索结果不陈旧；若后续需要可改为按路径/目录粒度失效。
- 只读 shell 命中后若文件随后被外部进程改动，缓存可能短暂陈旧；本进程内的写操作会失效缓存，跨进程不覆盖（已在风险表登记）。
