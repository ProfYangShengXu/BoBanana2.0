# BoBanana 2.0 项目说明（给人看的）

> **版本**：`2.1.5`（`portable-install`，2026-05-30）— 见根目录 `VERSION` 与 `bobanana/version.py`
> **读者**：产品、新同学、需要理解系统如何运行的开发者
> **运维**：通用清单见 `%USERPROFILE%\.cursor\skills\code-delivery-gate\ops\RUNBOOK.md`

---

## 这个项目是干什么的

BoBanana 2.0 是一个**纯终端编程 Agent**，用 Python + LangChain + LangGraph 搭建。
用户在终端里用自然语言下达编程任务，Agent 会先**规划**、再**逐步执行**（读写文件、跑命令），
并在每一环都有一个独立的**审查 Agent** 把关——这就是「变体 ReAct」：主 Agent 负责产出，
审查 Agent 负责挑错并给出可执行建议，主 Agent 据此修订，直到通过或用尽修订预算。

它还有**两层记忆**：工作记忆（对话窗口 + scratch）+ 结构化 SQLite（文件清单/事实/探索缓存）。交互完全在终端（rich 渲染），无 Web/GUI，风格仿 forge code。

**TUI 命令**：`/clear mind` 清空任务污染（轮次、探索缓存、plan/session facts），**保留** scratch 中的 workspace index 与 tool catalog；`/clear` 更彻底（含 scratch 全清）。

---

## 架构概览

```
            ┌──────────────────────── LangGraph ────────────────────────┐
 user task →│ prepare_workspace → plan → plan_review ──(revise)──┐         │
            │   │                                               ↓         │
            │   └──────(通过/超预算)──→ execute → exec_review ─(revise)─┐  │
            │                              ↑                           │  │
            │                              └─────(通过/超预算)→ advance ┘  │
            │                                          (还有步骤? → execute)│
            │                                          (无 → finalize)      │
            └────────────────────────────────────────────────────────────┘
   tools: read_file / write_file / list_dir / run_shell
   memory: working(窗口+scratch+关键词召回) + structured(SQLite 精确+探索缓存)
   流水线前置: intent(评估 size→缩放预算→是否元提示)；打招呼直接答跳过流水线
   执行中 shell 超时 ──→ replan(planner 改方案)
   每个 super-step 落 MemorySaver 检查点；任务超时/Ctrl-C 在节点边界中断 → 可 /resume /rollback
   审查驳回/replan ──→ 难度↑ ──→ 该步工具/步数预算↑（封顶 2×base）
```

| 层 / 模块 | 职责 | 主要路径 |
|-----------|------|----------|
| 入口 / TUI | REPL、命令分流、富文本渲染事件、`/open-folder` 与任务前元提示 | `bobanana/__main__.py`, `bobanana/tui.py` |
| 应用装配 | settings→logging→memory→skills/mcp→角色模型→graph，懒加载 LLM，离线自检，`set_workspace`/`classify_intent`/`apply_budget`/`chat_reply`/`triage_task` | `bobanana/app.py` |
| 编排 | LangGraph 节点与条件边（变体 ReAct）、按角色温度用模型、代码任务注入交付门、shell 超时→replan | `bobanana/graph.py` |
| Agent | intent（意图分级）/ planner（主-规划）/ reviewer（审查）/ executor（主-执行 ReAct）/ metaprompter（元提示）/ directive_gate（指令门） | `bobanana/agents/*.py` |
| 意图 / 元提示 / 工作区 | LLM 任务分级(intent) + 启发式兜底(triage) + 工作区选择器 | `bobanana/agents/intent.py`, `bobanana/triage.py`, `bobanana/workspace.py` |
| 记忆 | 工作（窗口+关键词召回）/ 结构化（含探索缓存）+ 统一门面 | `bobanana/memory/*.py` |
| 工具 | 文件读写列、受控 shell（超时→replan）、web（搜索/抓取/克隆）、skill、MCP | `bobanana/tools/*.py` |
| 技能 | 发现/解析/加载外部 SKILL.md，克隆技能库 | `bobanana/skills/registry.py` |
| MCP | 配置驱动加载 MCP 工具，优雅降级 | `bobanana/mcp/client.py` |
| 日志 | RichHandler 终端日志，级别可配/可切换 | `bobanana/logging_setup.py` |
| 基础 | 配置（预算缩放）/ LLM 工厂（角色温度）/ 状态模型 | `bobanana/{config,llm,state}.py` |

### 技能 / MCP / Web reach（本次新增）

- **技能（适配外部 SKILL.md）**：`SkillRegistry` 扫描 `~/.agents/skills`、`~/.cursor/skills`、
  `<workspace>/skills` 及克隆库，解析 front matter。agent 用 `list_skills` 看清单、
  `use_skill(name)` 读取指令并遵循（如 Agent-Reach 多平台路由），随后用 `run_shell` 调其 CLI。
  `--load-agent-reach` / `/load-agent-reach` 克隆 `Agent-Reach` 仓库到 `<data_dir>/external/` 并注册。
- **MCP**：读 `mcp.json`（`mcpServers` 映射）→ `langchain-mcp-adapters` 连接 → 工具并入执行器；
  无配置/无依赖/连接失败仅记日志并降级为空工具集。
- **Web 工具**：`web_search`（DuckDuckGo 无 key）、`fetch_url`（HTTP+正文抽取）、
  `clone_repo`（git 克隆并把代码索引进结构化记忆，实现「导入外部库/爬取外部代码」）。
- **日志**：`--debug` 或 `/debug on` 打开 DEBUG，终端实时看到 `node=…`、`tool call: …` 等运行轨迹便于排错。

### 可选工作区 / 元提示 / 交付门（本次新增）

- **可选代码工作区**：`/open-folder [path]` 调系统目录选择器（`workspace.py`，无 GUI 时降级为提示手输路径）；
  `app.set_workspace` 关闭旧记忆库句柄→在新工作区的 `<workspace>/.bobanana/` 重建结构化记忆与会话工作记忆→重置 skill_dirs/MCP/graph/toolbox（若 graph 仍绑定旧 memory/workspace 则 `_ensure_graph` 强制重建）。`prepare_workspace` 在 `workspace_root` 与当前目录不一致时会清空 scratch 索引缓存。`/workspace` 查看当前工作区与 data dir。
- **主动元提示**：提交任务前 `triage.should_metaprompt` 启发式判定「大/不清」（关键词、字数、并列/列表、模糊词、代码任务过短）；
  命中则 `MetaPrompter`（结构化 `TaskTriage`）择一：列澄清问题就地收集一轮回答，或给出细化需求供执行；LLM 异常回退原需求。
- **交付门 skill 默认调用**：`app` 启动加载本机 `code-delivery-gate` 的 `SKILL.md`，`graph` 在「代码任务」
  （`triage.is_code_task`）时把交付门要点注入 planner/executor/exec_review 系统提示，引导清理、自查逻辑链与自动化验证。可经 `BOBANANA_ENABLE_*` 关闭。

---

## 关键流程（逻辑链）

### 流程 A：一次编程任务（变体 ReAct 主链）

```
TUI 读取任务 → graph.run(把任务写入工作+向量记忆)
  → plan(planner 产出 Plan，含 key_directives) → plan_review(reviewer 评估)
      未通过且有预算 → revise_plan → plan(带建议重规划)
      通过/超预算 → execute(executor 跑 ReAct 工具循环完成当前步；注入 key_directives)
  → exec_review(reviewer 评估写入内容)
      未通过且有预算 → revise_exec → execute(带建议重做)
      通过 → advance(标记完成)；超预算未通过 → advance 仍标记完成但**如实计入 failed_steps**
  → 还有步骤 → execute
  → 全部步骤完成 → directive_gate(结构化判定 key_directives 是否全部满足)
      未满足且有预算 → 追加「[补救]」步骤 → execute
      全满足/超预算 → finalize(据 failed_steps+unmet 计算 status，如实汇总) → END
```

**硬审查闭环（honest finalize）**：审查未通过且重试预算耗尽时，为避免死循环仍会 `advance`，但**绝不伪装成功**——该步以 `[未通过审查]` 前缀记入 `failed_steps`。`finalize` 据 `failed_steps`、未满足 directives、门无法验证三类情形计算任务 `status`（`completed` / `partial`），partial 时切换为「诚实汇总」提示并逐条列出未通过步骤与遗留项；TUI 以黄色面板标注 PARTIAL。`directive_gate` 在产不出结构化结论时 fallback 改为**保守的 `all_satisfied=False`（不再默认放行）**，宁可报告「未验证」也不假定成功。

**重要指令门(directive_gate)**：planner 每回合产出可验证的 `key_directives`（如「文件确实写入磁盘」「构建运行并有输出」）。即使所有步骤都「完成」，未满足全部 directives 也不结束——门会把未满足项作为补救步骤回灌执行，`max_directive_revisions` 控制循环上限，超限则在总结中明确列出遗留项并标记 partial。

**提升通过率（不降低审查标准）**：executor 重试时收到**结构化修复指令**——区分两种情形：① 上一轮因工具步数耗尽（`Step stopped`）未完成，则判为「非质量失败」，指令其跳过重复探索、直奔核心写入/构建动作；② 质量被驳回，则把审查 suggestions 编号成 checklist 要求逐条解决，并明令禁止重复已失败或返回 `[cached]` 的工具调用、必须更换策略。配合默认 `max_tool_iters` 由 8 提升至 12（失败/空路径/缓存调用本就不计入预算），让重试真正有效而非空转。

**证据驱动审查（ground-truth review）**：此前 exec 审查只看 executor 返回的散文自述，审查器无法看到真实产物——「严格审查」名不副实。现改为：executor 在 ReAct 循环中收集 `last_evidence`（`write_file` 的路径+内容片段、`run_shell` 的命令+输出片段，有界截断）；`exec_review` 把证据块交给 `ReviewerAgent.review_artifact(evidence=…)`，提示词要求**只依据 EVIDENCE 块判定**，自述标注为 UNVERIFIED claim；无证据时默认不 approve（纯分析步除外）。审查器仍不持有工具，但评审对象从「自报」变为「真实写入/命令输出」。

**难度/预算去棘轮**：`tool_iter_bonus`（单步重试加成）在 `_advance_node` 后重置为 0，避免某步难导致后续所有步永久膨胀；`difficulty` 作为持久基线，每步有效额外预算 `= max(tool_iter_bonus, round(difficulty*max_tool_iters*0.5))`，大任务第一步就有 headroom。重规划预算耗尽时 `REPLAN_NEEDED` 哨兵改写为诚实失败文案，不泄漏进 step result / 记忆。工作记忆单条 turn 上限 2000 字符，防上下文无声膨胀。

**探索缓存**：`read_file`/`list_dir`/只读 shell 的结果按「工具+参数」为键缓存进结构化记忆（`exploration` 表）。相同探索再次调用直接命中返回（前缀 `[cached]`），且在 executor 中计为「非生产」不消耗工具预算，避免日志中常见的「反复 list_dir/read_file/dir 摸底直到超时」。任何写副作用（`write_file` 或写类 `run_shell`）成功后清空缓存，保证后续探索拿到最新状态。

**路径防打转（prepare_workspace + plan_validation）**：任务进入 `plan` 前先跑 `prepare_workspace`（无 LLM）写 scratch index/catalog；`plan_validation` 检查 phantom/未知路径、架构步数≤8、交付路径须在 `docs/delivery/output/`；`plan_review` 附带校验报告；架构大任务 `max_plan_revisions` 封顶 1；Executor 禁止 shell 摸底。

**报告可信度（report_validation）**：`exec_review` 校验含 FALSE_CLAIM（`_build_graph`、无路径遍历误报等）、**伪代码检测**（``` 块须出现在已读源码中）、**页眉 Agent 须为 BoBanana x.y.z**；测试数须先 `pytest --collect-only -q`（registry **写交付物前硬拦截**）；`pytest-cov` 等含官方 URL 则清除 needs_web；stale `.md` 拦截；磁盘 `validation_acceptable_ok` soft-pass；gate 可追加 `[补救/报告校验]`；finalize 与 gate 对齐 status。

**涉及文件**：`graph.py`、`workspace_index.py`、`plan_validation.py`、`report_validation.py`、`workspace_map.py`、`agents/planner.py`、`agents/reviewer.py`、
`agents/executor.py`、`tools/registry.py`（工具）、`memory/manager.py`（上下文与落库）。

### 流程 B：记忆路由（按信息类型分流）

```
对话轮次 → working.add_turn                          # 窗口 + 关键词召回(无嵌入)
写文件   → structured.upsert_file + set_fact         # 精确查询(文件清单/代码摘要)
探索工具 → structured.exploration 缓存               # 去重，不重复 list/read
取上下文 → manager.build_context(query) 聚合各层 → 注入各 Agent 提示
```

**涉及文件**：`memory/working_memory.py`、`memory/structured_memory.py`、
`memory/manager.py`、`tools/registry.py`（写文件副作用落库 + 探索缓存）。

### tools（集中注册表 + `.bobanana/tools/` 插件）

**两层结构**：

| 层级 | 路径 | 内容 |
|------|------|------|
| 核心注册 | `bobanana/tools/registry.py` | `Toolbox` 组装 core/skills/web/MCP；semver + 权限元数据 |
| Drop-in 插件 | `<workspace>/.bobanana/tools/` | `*.yaml` manifest 或 `@register_tool` 的 `*.py` |

**权限模型**（`bobanana/tools/permissions.py`）：`read` / `write` / `shell` / `network` / `admin`。每个工具声明所需权限；`BOBANANA_TOOL_PERMISSIONS` 配置授予集合，不足则返回 `ERROR: permission denied`。

**semver**：核心工具 `1.0.0`；插件在 YAML `version:` 或 `@register_tool(version=...)` 声明。

**Agent 内省（勿扫目录误报）**：
- 内置工具 **`describe_tool_registry`** → JSON 全量 catalog
- REPL：`/tools`、`/reload-tools`
- `--selfcheck` → `registry=… plugin_dir=… plugins_loaded=…`

**热加载**：改插件后 `/reload-tools` 或重启；`seed_plugin_directory` 首次创建 `.bobanana/tools/` 并复制示例 `example_ping.yaml` / `example_greet.py`。

**涉及文件**：`tools/registry.py`、`tools/plugin_registry.py`、`tools/permissions.py`、`tools/plugin_templates/*`。

---

### agents（变体 ReAct 角色 + 前置意图层）
- **IntentAgent**：`with_structured_output(Intent)` 一次调用给出 `task_size`(0~1)/`is_code_task`/`needs_metaprompt`；LLM 不可用时回退 `triage.py` 启发式估算，永不硬失败。
- **PlannerAgent**：用 `with_structured_output(Plan)` 产出/修订结构化步骤（含 key_directives）；收到审查建议（含超时重规划的合成审查）时带建议重规划。
- **ReviewerAgent**：用 `with_structured_output(ReviewResult)` 对「计划」和「写入内容」两类制品出结构化裁决（approved/score/suggestions/rationale）。**exec 审查**接收 executor 的 `last_evidence`（真实写入/命令输出），只据证据 approve，自述标注为 UNVERIFIED。
- **ExecutorAgent**：`bind_tools` 的有界 ReAct 循环；边跑边收集 `last_evidence`（write/shell 片段）；失败/缓存/空路径调用不计预算；检测 shell `ERROR: TIMEOUT` 即中止返回 `REPLAN_NEEDED`；重试时按情形给「直奔核心动作」或「编号 checklist + 禁止重复失败调用」的结构化修复指令。

### 角色温度（减少固化）
`llm.ROLE_TEMPERATURES`：reviewer/directive_gate=0（严格确定）、executor=0.45（破除重复探索）、planner/finalize=0.3、intent=0.2；未列角色回退全局 `temperature`。各角色由 `build_role_models` 各建一个 ChatOpenAI 实例，graph 按角色取用。

### 预算缩放（intent 驱动）
`Settings.scaled_budget(task_size)`：`effective = round(floor + (ceiling-floor)*t)`，clamp 到 `[floor, ceiling]`。配置值=天花板(t=1)，floors=地板(t=0)。打招呼极省、大重构拉满。`app.apply_budget` 应用并在变更时重建 graph。`.env` 天花板：steps=20 / tool_iters=24 / plan_rev=3 / exec_rev=3 / directive_rev=3 / shell_timeout=120。

### 动态难度（每个审查环自适应）
初始 `difficulty = intent.task_size`，随运行递增：exec 审查驳回（`_revise_exec_node`）按分数 +0.1~0.2 并加 `tool_iter_bonus += max(2, ⌈max_tool_iters*0.5⌉)`；shell 超时 replan 额外 `step_bonus += 2`、难度 +0.15。每步有效额外预算 `= max(tool_iter_bonus, round(difficulty*max_tool_iters*0.5))`（难度作持久基线，重试加成作单步 transient）；executor 封顶 `min(base+extra, base*2)`；`_advance_node` 重置 `tool_iter_bonus=0`（难度保留）。步数上限 `= max_steps + step_bonus`。

### 检查点 / 中断 / 续跑 / 回退（LangGraph MemorySaver）
- 图以 `compile(checkpointer=MemorySaver())` 编译（`enable_checkpoints`）；`run()` 用 `stream(..., stream_mode="values")` 逐 super-step 推进。
- **超时**：`task_timeout>0` 时设 `deadline`，每个节点边界检查；超限 → `_mark_interrupted("timeout")`。
- **Ctrl-C**：`try/except KeyboardInterrupt` 包裹 stream → `_mark_interrupted("user")`。
- 中断置 `interrupted`/`interrupt_reason`、发 `interrupted` 事件、保留 `_active_config`，返回最近快照（检查点仍可续）。
- **续跑** `resume()`：`stream(None, _active_config)` 从最近检查点继续（给新的时间预算）。
- **回退** `rollback(checkpoint_id)`：`stream(None, {thread_id, checkpoint_id})` 从指定检查点分叉续跑；`checkpoints()` 用 `get_state_history` 列出可选点。
- per-call `llm_timeout` 使每个节点有界，超时边界检测更及时（中断为**节点边界粒度**，不抢占节点内单次调用——文档明示此限制）。
- per-call LLM `timeout` 注入见 `llm.build_chat_model`。
- TUI：运行中提示「Ctrl-C 中断」；中断后 `_handle_interrupt` 询问 继续/回退/放弃/新指令；命令 `/resume`、`/rollback [编号]`。

### memory（两层）
- **working**：字符预算滚动窗口 + scratch；`recall_conversation` 用关键词（latin 词 + CJK 单字）重叠对窗口内轮次排序召回，无嵌入、零联网。
- **structured**：SQLite 四表（files / code_symbols / facts / exploration），按 path/key/category 精确查询；exploration 为探索缓存。

### tools（受控副作用）
- 文件操作限制在 workspace 根内（越界拒绝）；写文件同时落结构化记忆。
- shell 仅放行白名单首词 + 超时 kill（`settings.shell_timeout`）+ 输出截断，固定在 workspace 执行；超时返回 `ERROR: TIMEOUT` 信号 → executor 上抛 `REPLAN_NEEDED` → graph 重规划（受 `max_plan_revisions` 约束，耗尽则照常评审并如实记为失败）。

---

## 配置与运维（怎么跑、怎么查）

```powershell
# 简化启动器（推荐）
.\bb.cmd setup     # 首次：建 .venv 并装依赖（start 也会自动做）
copy .env.example .env   # 设置 OPENAI_API_KEY（联网运行必需）
.\bb.cmd config    # 或：交互式配置 API（OpenAI / DeepSeek 等）
.\bb.cmd start     # 跑测试通过后启动；.\bb.cmd use 快速启动

# macOS / Linux：./install.sh 首次安装；./bb.sh config / ./bb.sh start

# 或直接调用模块
python -m bobanana --configure  # 交互配置 API
python -m bobanana --selfcheck   # 离线自检（无需 key）
python -m bobanana               # 启动终端 Agent
```

**安装教程（幼儿园级）**：[`INSTALL.md`](../INSTALL.md)

| 操作 | 命令 |
|------|------|
| 启动（带测试） | `.\bb.cmd start` |
| 使用（免测试） | `.\bb.cmd use` |
| 关闭 | `.\bb.cmd close` |
| 重启 | `.\bb.cmd restart` |

| 操作 | 命令 / 说明 |
|------|-------------|
| 离线自检 | `python -m bobanana --selfcheck` |
| 离线测试 | `pytest`（默认排除 live；含检查点/中断/续跑/回退/难度等离线用例） |
| 真实 LLM 验收 | `pytest -m live`（需 OPENAI_API_KEY；真实建文件 + intent 分级，无 key 自动 skip） |
| 启动 | `python -m bobanana`，REPL 内 `/help /memory /recall <q> /clear /quit` |
| 任务预算 | 由 intent 的 `task_size` 自动缩放；`.env` 的 `BOBANANA_MAX_*` 为天花板 |

**验证结论（本次交付）**：导入 OK；`--selfcheck` 五项通过（graph 项在无 key 时按设计跳过并提示）；
离线 e2e `test_graph_runs_offline PASSED`（真实写出文件并落结构化记忆）。联网整链需用户提供 `OPENAI_API_KEY`。

---

## 近期交付与变更索引

| 日期 | 任务 | 更新日志 |
|------|------|----------|
| 2026-05-29 | 搭建编程 Agent（变体 ReAct + 多层记忆 + 终端交互） | [`docs/delivery/logs/2026-05-29-build-coding-agent.md`](delivery/logs/2026-05-29-build-coding-agent.md) |
| 2026-05-29 | 增加 skill / MCP / web 工具与日志模块（适配外部技能、装载 Agent-Reach、终端 debug） | [`docs/delivery/logs/2026-05-29-add-skills-mcp-logging.md`](delivery/logs/2026-05-29-add-skills-mcp-logging.md) |
| 2026-05-29 | 集成终端启动器 `bb`（start/use/close/restart，start 附带测试） | [`docs/delivery/logs/2026-05-29-cli-launcher.md`](delivery/logs/2026-05-29-cli-launcher.md) |
| 2026-05-29 | 可选工作区（`/open-folder`）+ 主动元提示 + 默认加载 code-delivery-gate | [`docs/delivery/logs/2026-05-29-workspace-metaprompt-gate.md`](delivery/logs/2026-05-29-workspace-metaprompt-gate.md) |
| 2026-05-29 | 重要指令门（key_directives 未满足不结束）+ 探索结果结构化缓存去重 | [`docs/delivery/logs/2026-05-29-directives-and-exploration-cache.md`](delivery/logs/2026-05-29-directives-and-exploration-cache.md) |
| 2026-05-29 | 硬审查闭环（未过/未验证不伪装成功，finalize 计算 status）+ 结构化重试指令提升通过率 | [`docs/delivery/logs/2026-05-29-harden-review-loop.md`](delivery/logs/2026-05-29-harden-review-loop.md) |
| 2026-05-29 | 砍向量记忆 + intent 意图分级与预算动态缩放 + 角色温度分层 + shell 超时触发重规划 | [`docs/delivery/logs/2026-05-29-intent-temps-shell.md`](delivery/logs/2026-05-29-intent-temps-shell.md) |
| 2026-05-29 | 天花板预算 + 检查点/中断 + 动态难度 + 中文 help + 真实 LLM e2e | [`docs/delivery/logs/2026-05-29-checkpoints-interrupt-difficulty.md`](delivery/logs/2026-05-29-checkpoints-interrupt-difficulty.md) |
| 2026-05-29 | 证据驱动审查 + 难度/预算去棘轮 + 哨兵不泄漏 + 上下文有界 | [`docs/delivery/logs/2026-05-29-review-groundtruth-budget.md`](delivery/logs/2026-05-29-review-groundtruth-budget.md) |
| 2026-05-30 | 工具注册表可发现性（catalog + /tools + selfcheck 纠正误报） | [`docs/delivery/logs/2026-05-30-tool-registry-discoverability.md`](delivery/logs/2026-05-30-tool-registry-discoverability.md) |
| 2026-05-30 | 插件体系（YAML+装饰器+semver+权限+describe_tool_registry） | [`docs/delivery/logs/2026-05-30-tool-plugins-permissions.md`](delivery/logs/2026-05-30-tool-plugins-permissions.md) |
| 2026-05-30 | 修复 5.30 运行：假 REPLAN / cached 预算 / read evidence / workspace map | [`docs/delivery/logs/2026-05-30-fix-530-run-failures.md`](delivery/logs/2026-05-30-fix-530-run-failures.md) |
| 2026-05-30 | report-truth 2.1.2：plan 误报、建议路径、FALSE_CLAIM、shell 拦截、磁盘终态 gate | [`docs/delivery/logs/2026-05-30-report-truth-2-fixes.md`](delivery/logs/2026-05-30-report-truth-2-fixes.md) |
| 2026-05-30 | report-truth 3（5.30-4）：FALSE_CLAIM 扩充、pytest 证据、md 拦截、gate/finalize 对齐 | [`docs/delivery/logs/2026-05-30-report-truth-3-5304-fixes.md`](delivery/logs/2026-05-30-report-truth-3-5304-fixes.md) |
| 2026-05-30 | report-truth 4（5.30-5）：伪代码检测、页眉 Agent、pytest 先于 write | [`docs/delivery/logs/2026-05-30-report-truth-4-5305-fixes.md`](delivery/logs/2026-05-30-report-truth-4-5305-fixes.md) |
| 2026-05-30 | portable-install 2.1.5：跨平台 install.py/sh、API 配置向导、幼儿园级 INSTALL.md | [`docs/delivery/logs/2026-05-30-portable-install-cross-platform.md`](delivery/logs/2026-05-30-portable-install-cross-platform.md) |

---

## 延伸阅读

- `README.md` — 安装与使用速览。
- `.env.example` — 全部可配置项。
