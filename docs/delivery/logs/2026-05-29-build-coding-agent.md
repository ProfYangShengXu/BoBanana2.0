# 更新日志 — 2026-05-29 · build-coding-agent

> **关联任务**：用 Python + LangChain + LangGraph 搭一个编程 Agent（变体 ReAct 规划/执行 + 多层记忆 + forge 风格纯终端交互）。
> **状态**：实施中
> **本文件用途**：写代码之前锁定计划与目标逻辑链；阶段二自查时逐条对照本文件。

---

## 1. 本次计划更新的内容

### 1.1 目标（完成后用户能做什么）

- [ ] 在终端运行 `python -m bobanana`，进入 forge 风格交互界面，向 Agent 下达编程任务。
- [ ] Agent 先规划（planner），由审查 agent（reviewer）评估并给出建议，主 agent 据建议修订计划——变体 ReAct 的「规划-审查」环。
- [ ] Agent 逐步执行（executor，ReAct + 工具调用：读/写/列文件、跑命令），每次写入内容由审查 agent 评估，主 agent 据建议修订——「执行-审查」环。
- [ ] 多层记忆：工作记忆（当前会话上下文）、向量记忆（对话信息模糊检索）、结构化记忆（重要信息/代码/文件列表精确检索）协同。
- [ ] 全程纯终端交互，富文本渲染（rich），无 Web/GUI。

### 1.2 计划改动范围（文件 / 模块）

| 路径 / 模块 | 计划动作 | 说明 |
|-------------|----------|------|
| `requirements.txt` / `.env.example` | 新增 | 依赖与配置模板 |
| `bobanana/config.py` | 新增 | 配置（LLM、嵌入、路径、循环上限） |
| `bobanana/llm.py` | 新增 | LLM / Embeddings 工厂（OpenAI 兼容，可配 base_url） |
| `bobanana/state.py` | 新增 | LangGraph 状态 TypedDict + 数据模型 |
| `bobanana/memory/working_memory.py` | 新增 | 工作记忆（token 受限滚动窗口 + 当前任务态） |
| `bobanana/memory/vector_memory.py` | 新增 | 向量记忆（Chroma，对话模糊检索） |
| `bobanana/memory/structured_memory.py` | 新增 | 结构化记忆（SQLite，文件/代码/事实精确检索） |
| `bobanana/memory/manager.py` | 新增 | 三层记忆统一门面，构建上下文 |
| `bobanana/tools/file_tools.py` | 新增 | 读/写/列/追加文件，写入即落结构化记忆 |
| `bobanana/tools/shell_tools.py` | 新增 | 受控 shell 执行 |
| `bobanana/tools/registry.py` | 新增 | 工具注册与 LangChain tool 封装 |
| `bobanana/agents/planner.py` | 新增 | 规划 agent（产出/修订步骤计划） |
| `bobanana/agents/reviewer.py` | 新增 | 审查 agent（评估计划与写入内容，结构化建议） |
| `bobanana/agents/executor.py` | 新增 | 执行 agent（单步 ReAct 工具循环） |
| `bobanana/graph.py` | 新增 | LangGraph 编排：规划→审查环→执行→审查环→收尾 |
| `bobanana/tui.py` | 新增 | forge 风格终端 UI（rich + prompt_toolkit） |
| `bobanana/app.py` / `bobanana/__main__.py` | 新增 | 应用装配与入口 |
| `README.md` / `docs/PROJECT.md` | 新增 | 文档 |

### 1.3 不在本次范围（明确不做）

- 不做 Web/GUI、不做多用户服务端。
- 不内置具体云端模型密钥；用户自配 `.env`。
- 不做真正的沙箱隔离（shell 工具仅做白名单 + 超时 + 工作区限制的轻量防护）。

### 1.4 依赖与前置条件

- Python 3.12；`langchain`、`langchain-openai`、`langgraph`、`langchain-chroma`、`chromadb`、`rich`、`prompt_toolkit`、`python-dotenv`、`pydantic`。
- 运行需 `OPENAI_API_KEY`（或兼容端点）；嵌入可配本地/远端，缺省可降级为离线哈希嵌入以保证向量库可空跑。

---

## 2. 目标逻辑链（阶段二对照 SSOT）

```
触发入口 → 输入校验 → 核心逻辑 → 持久化/副作用 → 返回/展示 → 失败与回滚
```

### 2.1 链路详述

| 环节 | 预期行为 | 关键文件/函数（计划） |
|------|----------|------------------------|
| 触发入口 | 终端 REPL 读取用户编程任务 | `tui.py: run_repl` → `app.py: Application.handle` |
| 输入校验 | 空输入忽略；`/help /memory /quit` 等命令分流；校验配置/LLM 可用 | `tui.py`, `config.py: Settings.validate` |
| 核心逻辑 | LangGraph 跑：planner→plan_review(loop)→executor(ReAct)→exec_review(loop)→下一步/finalize | `graph.py: build_graph`, `agents/*.py` |
| 持久化/副作用 | 文件写入落盘 + 进结构化记忆；对话进向量记忆；步骤产出进工作记忆 | `tools/file_tools.py`, `memory/*` |
| 返回/展示 | rich 渲染计划、审查意见、步骤执行、最终总结 | `tui.py: render_*` |
| 失败与回滚 | LLM/工具异常捕获并展示；审查循环有最大次数；shell 超时/越界拒绝 | `graph.py`, `tools/shell_tools.py`, `agents/executor.py` |

### 2.2 验收标准（可观测）

- [ ] `python -c "import bobanana.graph"` 等核心模块可导入无错。
- [ ] 离线（无 API key）下 `python -m bobanana --selfcheck` 能装配图、记忆三层可读写、不崩溃。
- [ ] 提供 `OPENAI_API_KEY` 后可完成一次「规划→审查→执行→审查→产出文件」闭环（人工/集成层面，文档给出步骤）。

### 2.3 风险与边界

| 场景 | 预期处理 |
|------|----------|
| 无 API key | 工厂报清晰错误；`--selfcheck` 用离线嵌入与桩 LLM 不触网 |
| 审查无限循环 | `max_plan_revisions` / `max_exec_revisions` 上限后强制放行 |
| 工具写文件越界 | 限制在工作区根目录内，拒绝绝对/越界路径 |
| shell 危险命令/超时 | 命令前缀白名单 + 超时 kill + 返回截断 |
| 向量库为空检索 | 返回空列表，上下文构建容错 |

---

## 3. 实施记录（写代码过程中可追加）

| 时间 | 实际改动 | 与计划差异 |
|------|----------|------------|
| 2026-05-29 | 初始化全部模块（config/llm/state/memory*4/tools*3/agents*3/graph/tui/app/__main__） | 无 |
| 2026-05-29 | 新增 `tests/test_graph_offline.py`（stub LLM 跑通全图，离线） | 计划外补充，增强验证 |
| 2026-05-29 | 新增 `.gitignore`；清理 `state.py` 未用 `_take_last`/`Literal` | 阶段一清理 |
| 2026-05-29 | 实际安装 langchain/langgraph 1.x（>= 约束解析到最新主版本），API 兼容无需改代码 | 版本高于示例，已验证兼容 |

---

## 4. 阶段二自查结论（交付前填写）

- [x] 入口与计划一致：`__main__.main` → `TerminalUI.run`/`--selfcheck`；REPL 命令分流与任务执行均存在且可达。
- [x] 数据流与计划一致：`graph.run` → plan → plan_review →(条件)→ execute(ReAct 工具循环) → exec_review →(条件)→ advance → finalize；离线 e2e 测试验证整条链路。
- [x] 分支与失败路径与计划一致：审查未通过且未超预算→回改节点；超预算→放行；工具异常/越界/超时返回 ERROR 字符串交回模型；finalize/LLM 异常有兜底。
- [x] 验收标准已满足：`import bobanana.graph` 等导入 OK；`--selfcheck` 五项（其中 graph 需 key 时跳过说明）；离线 e2e 测试 `test_graph_runs_offline PASSED`（真实写出 hello.txt 并落结构化记忆）。

**偏差说明**（若无写「无」）：

- 依赖解析到 LangChain/LangGraph 1.x（高于 `.env.example`/计划示例的 0.x），构造期 API（`with_structured_output`/`bind_tools`/`StructuredTool.from_function`/`StateGraph`）兼容，已通过测试，无需改动代码。
- 真实 LLM 闭环（联网调用）需用户提供 `OPENAI_API_KEY`，属计划 §1.4 前置；已用 stub LLM 在离线层面验证等价逻辑链路。
