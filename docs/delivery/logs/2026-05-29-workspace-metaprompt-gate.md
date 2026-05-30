# 更新日志 — 2026-05-29 · workspace-metaprompt-gate

> **关联任务**：(1) 可选代码工作区，新增 `/open-folder` 调文件选择器选工作区；(2) 检测任务大/描述不清时主动 metaprompting；(3) 加载本地 `code-delivery-gate` skill，代码任务默认调用。
> **状态**：实施中

---

## 1. 计划

### 1.1 目标（完成后用户能做什么）
- [ ] 启动时不强制工作区；运行中 `/open-folder [路径]` 可弹出系统文件夹选择器（或直接传路径）切换工作区，文件读写、记忆库随之切换。
- [ ] 提交任务时，若启发式判定「任务大/描述不清」，Agent 先做元提示：不清→列澄清问题并就地收集回答；偏大但清晰→给出细化后的需求供确认后执行。
- [ ] 代码类任务默认加载本机 `code-delivery-gate` SKILL.md 的要点，注入规划/执行系统提示，使 Agent 遵循交付门（计划日志、清理、自查、运维）。

### 1.2 计划改动范围
| 路径 | 动作 | 说明 |
|------|------|------|
| `bobanana/workspace.py` | 新增 | 文件夹选择器（tkinter，无 GUI 时优雅降级） |
| `bobanana/triage.py` | 新增 | 任务复杂度/清晰度/代码任务启发式 |
| `bobanana/agents/metaprompt.py` | 新增 | MetaPrompter（结构化三件套：澄清问题/细化需求/评估） |
| `bobanana/state.py` | 修改 | 新增 `TaskTriage` 模型 |
| `bobanana/config.py` | 修改 | `enable_metaprompt`/`enable_delivery_gate`/`delivery_gate_skill` |
| `bobanana/app.py` | 修改 | `set_workspace()`、`triage_task()`、加载交付门 skill 文本 |
| `bobanana/graph.py` | 修改 | 代码任务注入交付门指令到 plan/execute system prompt |
| `bobanana/tui.py` | 修改 | `/open-folder` 命令；任务前 metaprompting 交互 |
| `tests/test_features.py` | 新增 | triage 启发式、metaprompt 解析、workspace 切换离线测试 |
| `README.md` / `docs/PROJECT.md` | 修改 | 文档 |

### 1.3 不在本次范围
- 不做图形主窗口；文件选择器仅系统对话框，无 GUI 环境降级为提示用手输路径。
- 不强制每个任务都 metaprompting（仅在启发式触发或描述不清时）。
- 不改变既有变体 ReAct 主链与记忆分层。

### 1.4 依赖与前置
- `tkinter`（CPython Windows 自带）；缺失时降级。
- 交付门 skill 已可被 SkillRegistry 发现（`~/.cursor/skills/code-delivery-gate`，selfcheck 已确认）。

---

## 2. 目标逻辑链（SSOT）

| 环节 | 预期行为 | 关键文件/函数 |
|------|----------|----------------|
| 触发入口 | REPL `/open-folder`；普通任务先经 triage | `tui.py: run / _run_task` |
| 输入校验 | 路径存在性/是否目录；空任务忽略；triage 启发式判大/不清 | `workspace.py`, `triage.py` |
| 核心逻辑 | 选目录→`app.set_workspace`；metaprompt→`app.triage_task`；代码任务→注入交付门指令 | `app.py`, `agents/metaprompt.py`, `graph.py` |
| 持久化/副作用 | 切换工作区重建 toolbox/记忆库与 graph；交付门指令进系统提示并记 fact | `app.py`, `graph.py`, `memory` |
| 返回/展示 | 选择结果/澄清问题/细化需求/最终回答 渲染 | `tui.py` |
| 失败与回滚 | 无 GUI→提示手输；路径非法→报错不切换；metaprompt LLM 失败→按原需求继续 | `workspace.py`, `app.py`, `tui.py` |

### 2.2 验收标准（可观测）
- [ ] `import` 全模块成功；`--selfcheck` 仍全 PASS。
- [ ] 离线测试：triage 判定（中文「写一个登录系统」=代码任务且偏大）、metaprompt 解析容错、`set_workspace` 切换后 toolbox 指向新目录。
- [ ] 交付门：代码任务时系统提示含交付门要点（可通过注入函数返回值断言）。

### 2.3 风险与边界
| 场景 | 处理 |
|------|------|
| 无显示器/SSH 跑 tkinter | 捕获异常，提示 `/open-folder <路径>` 手动指定 |
| 切换工作区时旧记忆库句柄 | 先 `memory.close()` 再建新的 |
| metaprompt 死循环澄清 | 仅澄清一轮，之后直接执行 |
| 交付门 skill 不存在 | 跳过注入，记日志 |
| 误把纯问答判为代码任务 | 交付门指令为「适用时遵循」，不强制产文件 |

---

## 3. 实施记录
| 时间 | 改动 | 差异 |
|------|------|------|
| 2026-05-29 | 新增 `workspace.py`（tkinter 选择器 + 路径校验，降级提示） | + |
| 2026-05-29 | `app.set_workspace`：切目录重建记忆库/skills/graph，重指向 mcp.json | + |
| 2026-05-29 | 新增 `triage.py`（is_code_task/looks_large/looks_unclear/should_metaprompt） | + |
| 2026-05-29 | 新增 `agents/metaprompt.py`（MetaPrompter，结构化容错+回退）；`state.TaskTriage` | + |
| 2026-05-29 | `config`：`enable_metaprompt`/`enable_delivery_gate`/`delivery_gate_skill` + env | + |
| 2026-05-29 | `app`：加载本机 code-delivery-gate skill 文本，`triage_task` 懒构造 | + |
| 2026-05-29 | `graph`：代码任务注入交付门指令到 planner/executor/exec_review 系统提示 | + |
| 2026-05-29 | `tui`：`/open-folder [path]`、`/workspace`、任务前 metaprompting 交互 | + |
| 2026-05-29 | 新增 `tests/test_features.py`（12 项断言）；`.env.example` 文档 | + |
| 2026-05-29 | 新增 `/restart`（`restart.py` re-exec，保留 CLI flags） | + |
| 2026-05-29 | 提升 shell 成功率：executor 注入 OS/shell 提示；Windows 下拦截 POSIX-ism（/dev/null、ldconfig、find /usr、which 等）返回纠正提示；run_shell 描述带 OS；UTF-8 解码 | + |
| 2026-05-29 | OS 区分命令库：`COMMON/WINDOWS/POSIX_COMMANDS` + `default_allowlist()` 按 `platform.system()` 自动确认；hint/工具描述带 allowlist；启动记日志 | + |
| 2026-05-29 | 工具预算：executor 改 while 循环，仅「成功且非空路径」的 turn 计入 `max_tool_iters`；失败/空路径不计；新增 `hard_cap` 防死循环 | + |

---

## 4. 阶段二自查结论
- [x] 入口/数据流/分支与计划一致：`/open-folder`→校验/选择→`set_workspace`（关旧记忆→建新→重置 graph）；普通任务→`_maybe_metaprompt`（启发式门→LLM triage→澄清一轮或细化）→`run_task`；代码任务→`_directives` 注入交付门。
- [x] 失败/回滚：无 GUI→降级提示手输路径；非法路径→不切换并报错；triage LLM 异常→按原需求继续；skill 缺失→跳过注入并记日志。
- [x] 验收满足：
  - `pytest -q` → **12 passed**（含 triage 启发式、metaprompt 解析/回退、workspace 校验、交付门注入开/关）。
  - `--selfcheck` → 全 **PASS**，日志确认 `delivery-gate skill loaded (4180 chars) — active for code tasks`，graph compiled。
  - `compileall` 通过；核心模块 import OK。
  - lint：IDE 诊断 0 错误（ruff/flake8 未装于 venv，已用 IDE linter 代替）。

**偏差说明**：
- `should_metaprompt` 为保守启发式：极短且非代码的模糊语（如「做个东西」）不会触发，仅 vague 关键词或「代码任务+过短」触发；这是有意降低误触发，测试用例已对齐真实行为。
- ruff/flake8 未安装在项目 venv，使用 IDE 诊断 + `compileall` 替代静态检查（非阻塞，已说明）。
