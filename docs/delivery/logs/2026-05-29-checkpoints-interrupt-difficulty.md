# 更新日志 — 2026-05-29 · 天花板预算 + 真实 LLM 验收 + 动态难度 + 检查点/中断 + 中文 help

> **关联任务**（五项）：
> 1. 调整 env 任务天花板预算（intent 会向下缩放，故抬高上限，并新增超时类配置）。
> 2. 测试端优化：建立「真实 LLM 端到端验收」（按 OPENAI_API_KEY 门控的 e2e 测试）。
> 3. 每个推理/审查环动态调整当前任务难度（审查驳回/重规划 → 难度递增 → 加大该步工具/步数预算）。
> 4. 检查点 + 中断机制：可回退；任务超时未完成或用户 Ctrl-C 可中断回答，等待进一步指令（继续/回退/放弃/新指令）。
> 5. `/help` 改为中文。
> **技术底座**：LangGraph 1.2.2 `MemorySaver` 检查点（已实测 `stream(values)`/`get_state_history`/`invoke(None,cfg)` 续跑与按 checkpoint_id 回退）。
> **状态**：已完成（40 离线用例通过，2 真实 LLM 用例 `-m live` 实测通过 170s）

---

## 1. 计划

### 1.1 改动范围
| 路径 | 动作 | 说明 |
|------|------|------|
| `.env` / `.env.example` | 修改 | 抬高天花板；加 `BOBANANA_TASK_TIMEOUT`/`BOBANANA_LLM_TIMEOUT`/`BOBANANA_ENABLE_CHECKPOINTS` |
| `bobanana/config.py` | 修改 | 加 `task_timeout`/`llm_timeout`/`enable_checkpoints`；默认上限抬高 |
| `bobanana/llm.py` | 修改 | `build_chat_model` 注入 per-call `timeout`（bound 每个节点，利于超时边界检测） |
| `bobanana/state.py` | 修改 | 加 `difficulty`/`tool_iter_bonus`/`step_bonus`/`interrupted`/`interrupt_reason`；new_state 接受初始难度 |
| `bobanana/agents/executor.py` | 修改 | `execute(..., extra_tool_iters)`，有效预算=min(base+bonus, base*2) |
| `bobanana/graph.py` | 修改 | 编译挂 MemorySaver；`run` 改流式+截止时间+Ctrl-C 捕获+检查点；`resume`/`rollback`/`checkpoints`；难度递增（revise_exec/replan）；execute 注入 bonus；advance 用 max_steps+step_bonus |
| `bobanana/app.py` | 修改 | `run_task` 透传初始难度=intent size；`resume_task`/`rollback_task`/`list_checkpoints` 门面 |
| `bobanana/tui.py` | 修改 | HELP 中文化；中断后交互（继续/回退/放弃/新指令）；`/resume` `/rollback`；渲染 difficulty/interrupted 事件 |
| `tests/test_e2e_live.py` | 新增 | 真实 LLM e2e（无 key 自动 skip） |
| `tests/test_features.py` | 修改 | +难度递增、超时中断、resume 续跑、rollback、executor extra_iters |
| `README.md`/`docs/PROJECT.md` | 修改 | 文档 |

### 1.2 难度递增策略
- 初始 `difficulty = intent.task_size`。
- exec 审查未过且重试：`difficulty = min(1, difficulty + (0.2 if score<4 else 0.1))`；`tool_iter_bonus += max(2, ceil(max_tool_iters*0.5))`。
- shell 超时 replan：`step_bonus += 2`，`difficulty += 0.15`。
- 执行有效工具预算 = `min(max_tool_iters + tool_iter_bonus, max_tool_iters*2)`（硬顶，防失控）。
- 步数上限 = `max_steps + step_bonus`（仍受 recursion_limit 约束）。

### 1.3 检查点/中断/回退（MemorySaver）
- 编译 `compile(checkpointer=MemorySaver())`；`run` 用 `stream(state, {configurable:{thread_id}, recursion_limit}, stream_mode="values")`。
- 截止：`task_timeout>0` 时设 `deadline=monotonic()+timeout`；每个 super-step 边界检查超限 → 中断（reason=timeout）。
- Ctrl-C：`try/except KeyboardInterrupt` 包裹 stream → 中断（reason=user）。
- 中断：置 `interrupted=True`/`interrupt_reason`，发 `interrupted` 事件，保存 `_active_config`/`_interrupted`，返回最近快照。
- 续跑 `resume()`：`stream(None, _active_config, values)` 从最近检查点继续。
- 回退 `rollback(checkpoint_id)`：`stream(None, {thread_id, checkpoint_id}, values)` 从指定检查点分叉续跑。
- `checkpoints()`：`get_state_history(_active_config)` → 列出 (checkpoint_id, current_step, next 节点)。
- per-call LLM `timeout=llm_timeout` 使节点有界，超时边界检测更及时（节点内单次调用不被硬抢占，文档说明此边界粒度）。

### 1.4 不在本次范围
- 不做跨进程持久化检查点（MemorySaver 为进程内；重启后历史不保留）。
- 不抢占式杀死正在执行的单次工具/LLM 调用（边界级中断 + per-call 超时已覆盖常见卡顿）。

---

## 2. 目标逻辑链（SSOT）
| 环节 | 预期 | 文件 |
|------|------|------|
| 入口 | TUI→intent→apply_budget→run_task(初始难度=size) | tui/app |
| 流式执行 | stream(values)+检查点；边界查超时；捕获 Ctrl-C | graph.run |
| 难度自适应 | 驳回/重规划→难度↑→该步预算↑ | graph._revise_exec/_replan/_execute |
| 中断 | 超时/用户→interrupted+reason+事件，留检查点 | graph._interrupt |
| 续跑/回退 | resume(None,cfg) / rollback(checkpoint_id) | graph.resume/rollback |
| 交互 | 中断后 prompt：继续/回退/放弃/新指令 | tui._handle_interrupt |
| 验收 | 离线 stub 全过 + 真实 LLM e2e（有 key 才跑） | tests |

### 2.2 验收
- [ ] 全模块 import；`--selfcheck` PASS；既有 35 测试仍过。
- [ ] 新增离线：超时→interrupted、resume 续到 done、rollback 到早期检查点、难度随驳回递增、executor extra_iters 生效。
- [ ] `tests/test_e2e_live.py` 在无 key 时 skip、有 key 时真实建文件并 status=completed。
- [ ] `/help` 全中文。

### 2.3 风险
| 场景 | 处理 |
|------|------|
| 节点内单次调用卡死 | per-call `llm_timeout`/`shell_timeout` 兜底；中断为边界粒度（文档说明） |
| 难度膨胀失控 | tool_iters 硬顶=base*2；step 受 recursion_limit |
| 检查点累积内存 | 进程内、单任务规模可控；不持久化 |
| 续跑 thread 串味 | 每个新任务 uuid thread_id |
| 旧测试无新字段 | new_state 默认值 |

---

## 3. 实施记录
| 时间 | 改动 | 差异 |
|------|------|------|
| 2026-05-29 | config/.env 抬高天花板 + task/llm timeout + enable_checkpoints | `task_timeout` 改 `float`（便于亚秒测试），其余按计划 |
| 2026-05-29 | state 加 difficulty/bonus/interrupt 字段；new_state(initial difficulty) | 按计划 |
| 2026-05-29 | executor `extra_tool_iters`，有效预算 min(base+bonus, base*2) | 按计划 |
| 2026-05-29 | graph：MemorySaver 编译 + 流式 run + 超时/Ctrl-C + resume/rollback/checkpoints + 难度递增 | 按计划 |
| 2026-05-29 | app 门面 resume_task/rollback_task/list_checkpoints；run_task 透传难度 | 按计划 |
| 2026-05-29 | tui：HELP 中文化 + 中断交互 + /resume /rollback + 事件渲染 | 按计划 |
| 2026-05-29 | tests：离线（难度/超时中断/续跑/回退/extra_iters）+ live e2e；pytest.ini + conftest 加载 .env | 默认 `-m "not live"` 排除 live |
| 2026-05-29 | README/PROJECT.md 文档 | 按计划 |

---

## 4. 阶段二自查结论
- [x] 入口/数据流/分支与计划一致：TUI→intent→run_task(难度)→stream(检查点)→中断/续跑/回退闭环。
- [x] 验收满足：`pytest` 40 passed / 2 deselected；`pytest -m live` 2 passed（真实建出 hello.txt、intent 分级正确）；`--selfcheck` 全 PASS；图编译挂 MemorySaver。

**偏差说明**：`task_timeout` 由 `int` 改为 `float`（秒），以支持测试中的亚秒级超时验证，对外语义不变（仍是秒，`0`=禁用）。live 测试默认排除（`addopts = -m "not live"`），需 `pytest -m live` 显式触发以免每次跑都消耗 token。
