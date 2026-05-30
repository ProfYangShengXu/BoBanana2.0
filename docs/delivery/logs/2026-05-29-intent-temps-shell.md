# 更新日志 — 2026-05-29 · intent-layer + temp-tiers + shell-replan

> **关联任务**（四项）：
> 1. **砍掉向量记忆**：移除 ChromaDB/VectorMemory 与 embeddings 整条链路；会话回忆改由工作记忆关键词召回。
> 2. **新增 intent 层**：LLM 结构化输出判定 `needs_metaprompt` 与 `task_size`（0=打招呼 ~ 1=重构大项目），据 task_size 动态缩放 config 预算默认值；极小非代码任务直接对话短路，不启动规划流水线。
> 3. **温度分层**：按角色分配温度（reviewer/gate 严格=0；executor 较高=0.45 破除固化重复；planner/finalize/intent 居中），减少 temperature=0.1 一刀切导致的探索脚本固化。
> 4. **shell run 安全性**：同步 wait 结果；命令超时 → 返回 TIMEOUT 信号 → 触发重规划（planner 收到「上轮方案超时」反馈改方案），受 max_plan_revisions 约束，耗尽则如实评审失败。
> **状态**：已完成（35 tests + selfcheck PASS + intent 实测）

---

## 1. 计划

### 1.1 改动范围
| 路径 | 动作 | 说明 |
|------|------|------|
| `bobanana/memory/vector_memory.py` | **删除** | 砍掉向量层 |
| `bobanana/memory/manager.py` | 修改 | 去 embeddings/vector；`recall_conversation` 改工作记忆关键词召回 |
| `bobanana/llm.py` | 修改 | 删 HashingEmbeddings/build_embeddings；加 `build_chat_model(temperature=)`、`ROLE_TEMPERATURES`、`build_role_models` |
| `bobanana/state.py` | 修改 | 新增 `Intent` 模型 |
| `bobanana/agents/intent.py` | **新增** | IntentAgent：结构化分类 + 启发式 fallback |
| `bobanana/agents/__init__.py` | 修改 | 导出 IntentAgent |
| `bobanana/config.py` | 修改 | 删 embedding 配置；加 `enable_intent`、`shell_timeout`、预算缩放 `scaled_budget(task_size)` + floors |
| `bobanana/app.py` | 修改 | 去 embeddings；role 模型缓存并注入 graph；`classify_intent`/`apply_budget`/`chat_reply`；selfcheck 调整 |
| `bobanana/graph.py` | 修改 | 接收 `models` 按角色用模型；shell 超时 `execute→replan→plan` 路由；recursion 余量 |
| `bobanana/agents/executor.py` | 修改 | 检测 `ERROR: TIMEOUT` → 中止步返回 `REPLAN_NEEDED:` |
| `bobanana/tools/shell_tools.py` | 修改 | 超时信息标准化为 TIMEOUT 重规划提示；timeout 由 settings 注入 |
| `bobanana/tools/registry.py` | 修改 | Toolbox 透传 shell_timeout |
| `bobanana/tui.py` | 修改 | _run_task：intent→缩放→打招呼短路→metaprompt(由 intent 驱动)→run |
| `.env.example` | 修改 | 删 embedding；加 BOBANANA_ENABLE_INTENT / BOBANANA_SHELL_TIMEOUT |
| `tests/*` | 修改 | 去 HashingEmbeddings；加 intent/缩放/温度/超时重规划测试 |
| `requirements.txt`/`README`/`docs/PROJECT.md` | 修改 | 去 chroma 依赖说明；补文档 |

### 1.2 预算缩放（floor + (configured-floor)*t，四舍五入，clamp）
| 项 | floor | 上限(=config) |
|----|-------|----------------|
| max_steps | 2 | settings.max_steps |
| max_tool_iters | 4 | settings.max_tool_iters |
| max_exec_revisions | 1 | settings.max_exec_revisions |
| max_plan_revisions | 1 | settings.max_plan_revisions |
| max_directive_revisions | 1 | settings.max_directive_revisions |
| shell_timeout | 20 | settings.shell_timeout |

> 含义：打招呼 t≈0 → 取 floor（极省）；大重构 t≈1 → 取用户配置上限。env 显式上限始终是天花板。

### 1.3 角色温度
planner 0.3 / executor 0.45 / reviewer 0.0 / directive_gate 0.0 / finalize 0.3 / intent 0.2（global `temperature` 作未列角色兜底）。

### 1.4 不在本次范围
- 不改 shell 组合命令白名单绕过（安全专项另议）。
- 不引入语义向量替代品（关键词召回已满足近期需求）。

---

## 2. 目标逻辑链（SSOT）
| 环节 | 预期 | 文件 |
|------|------|------|
| 输入 | TUI 收到任务 | tui._run_task |
| intent | LLM 结构化判 size/metaprompt；失败回退启发式 | agents/intent.py |
| 缩放 | task_size → settings 预算；变更则重建 graph | app.apply_budget |
| 短路 | size 极小且非代码 → chat_reply 直接答，不进图 | app.chat_reply |
| metaprompt | intent.needs_metaprompt 才跑 | tui._maybe_metaprompt |
| 规划/执行/审查 | 角色各自温度；reviewer/gate=0 严格 | graph + 角色模型 |
| shell 超时 | TIMEOUT→executor 中止→graph 重规划(≤max_plan_revisions)→否则评审失败 | shell_tools/executor/graph |
| 记忆 | 工作记忆窗口 + 关键词召回 + 结构化事实/文件/探索缓存 | memory/manager |

### 2.2 验收
- [ ] 全模块 import；`--selfcheck` 全 PASS（无 embeddings 项，memory 召回工作）。
- [ ] 既有离线测试更新后通过；新增：intent 解析/fallback、缩放边界（t=0→floor, t=1→上限）、角色温度映射、shell 超时→重规划 once、超时预算耗尽→评审失败。
- [ ] 无残留 chroma/embeddings 引用。

### 2.3 风险
| 场景 | 处理 |
|------|------|
| intent LLM 失败 | 回退 triage 启发式估 size + needs_metaprompt |
| 重规划死循环 | max_plan_revisions 约束；耗尽走 exec_review 如实失败 |
| 缩放使大任务步数不足 | 上限=用户 config，可经 env 调高 |
| 旧 .bobanana/chroma 残留 | 不再读取，无害；不主动删用户数据 |

---

## 3. 实施记录
| 时间 | 改动 | 差异 |
|------|------|------|
| 2026-05-29 | 砍向量 | 删 `memory/vector_memory.py`；`manager` 去 embeddings、`recall_conversation` 改关键词召回；`llm` 删 HashingEmbeddings/build_embeddings；`config` 删 embedding 配置；`app` 去 embeddings、selfcheck 调整；requirements 删 chroma；.env/.env.example/bb.ps1/install.ps1 去 embedding 残留 |
| 2026-05-29 | 温度 | `llm.ROLE_TEMPERATURES`/`build_chat_model(temperature=)`/`build_role_models`/`role_temperature`；`app` 缓存角色模型注入 graph；`graph` 接收 `models` 按角色用模型（reviewer/gate=0、executor=0.45…），finalize 用 finalize 模型 |
| 2026-05-29 | intent | `state.Intent`；`agents/intent.py`（结构化+启发式 fallback）；`config.enable_intent`+`scaled_budget`+floors；`app.classify_intent`/`apply_budget`/`chat_reply`；`tui._intent_and_budget` + 打招呼短路 + 由 intent 驱动元提示 |
| 2026-05-29 | shell | `shell_tools` 超时返回 `ERROR: TIMEOUT…`；`config.shell_timeout` 注入 Toolbox/ShellRunner；`executor` 检测 TIMEOUT→`REPLAN_NEEDED`；`graph` `_route_after_execute`/`_replan_node`/replan 节点与边、recursion 余量；tui 渲染 replan 事件 |
| 2026-05-29 | 测试 | 去 HashingEmbeddings；+intent 解析/clamp/fallback、scaled_budget 边界、角色温度、shell 超时标记、executor REPLAN 信号、图级超时→replan e2e（共 +7，合计 35 passed） |

---

## 4. 阶段二自查结论
- [x] 入口/数据流/分支与计划一致：TUI→intent(size/metaprompt)→apply_budget→(打招呼短路 | metaprompt)→graph；图内 execute 超时→replan→plan，角色各自温度，reviewer/gate 严格=0。
- [x] 验收满足：`pytest -q` **35 passed**；`--selfcheck` 全 PASS（无 embeddings 项、memory 关键词召回工作、graph compiled）；intent 实测：「你好」→size=0.0/非代码/不元提示；「重构整个支付模块…」→size=0.75/代码/需元提示。
- [x] 无残留 chroma/embeddings 运行期引用（仅历史交付日志保留记录）。

**偏差说明**：`done` 字段语义不变；预算缩放选择「floor+(ceiling-floor)*t」而非直接替换默认值，使 env 配置始终为天花板、打招呼任务自动省钱。角色模型用「每角色一个 ChatOpenAI 实例」而非 `.bind(temperature=)`，因结构化输出包装后 bind 温度不可靠。
