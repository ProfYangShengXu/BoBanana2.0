# 更新日志 — 2026-05-29 · add-skills-mcp-logging

> **关联任务**：增加 skill 模块与 MCP 模块（网页搜索、适配外部 skills、装载 Agent-Reach 以导入外部库/爬取外部代码），并增加日志模块让用户在终端看到 agent 运行过程便于 debug。
> **状态**：实施中
> **本文件用途**：写代码之前锁定计划与目标逻辑链；阶段二自查时逐条对照本文件。

---

## 1. 本次计划更新的内容

### 1.1 目标（完成后用户能做什么）

- [ ] 终端可见 agent 运行过程：`--debug` 或 `/debug` 打开详细日志（节点、Agent 调用、工具调用、错误、耗时），rich 渲染。
- [ ] skill 模块：自动发现并「适配」外部 SKILL.md 技能（`~/.agents/skills`、`~/.cursor/skills`、工作区 `skills/`、克隆库）；agent 可 `list_skills` / `use_skill(name)` 读取并遵循其指令。
- [ ] 装载 Agent-Reach：`--load-agent-reach` / `/load-agent-reach` 克隆 `https://github.com/Panniantong/Agent-Reach.git` 到数据目录并注册其技能；agent 据其 SKILL.md 经 shell 调用 agent-reach/curl/gh 等完成 17 平台访问。
- [ ] MCP 模块：读 `mcp.json` 配置驱动加载 MCP 工具并注入执行器；无配置/无依赖/连接失败均优雅降级（仅记日志，不崩溃）。
- [ ] 网页搜索与外部代码获取：内置无 key 工具 `web_search`（DuckDuckGo）、`fetch_url`（HTTP+正文抽取）、`clone_repo`（git 克隆并索引到结构化记忆），实现「导入外部库/爬取外部代码」。

### 1.2 计划改动范围（文件 / 模块）

| 路径 / 模块 | 计划动作 | 说明 |
|-------------|----------|------|
| `bobanana/logging_setup.py` | 新增 | RichHandler 日志，级别可配 |
| `bobanana/skills/registry.py` + `__init__.py` | 新增 | 扫描/解析/加载外部 SKILL.md，克隆技能库 |
| `bobanana/mcp/client.py` + `__init__.py` | 新增 | 配置驱动加载 MCP 工具，优雅降级 |
| `bobanana/tools/web_tools.py` | 新增 | web_search / fetch_url / clone_repo |
| `bobanana/tools/registry.py` | 修改 | 注册 web 工具、skill 工具、合并 MCP 工具 |
| `bobanana/tools/shell_tools.py` | 修改 | 白名单加入 agent-reach/mcporter/yt-dlp/rdt/twitter/curl |
| `bobanana/config.py` | 修改 | 新增 log_level/skill_dirs/mcp_config/agent_reach_repo/enable_web_tools |
| `bobanana/graph.py` | 修改 | 节点/工具日志；合并 MCP 工具；执行器异步工具兜底 |
| `bobanana/agents/executor.py` | 修改 | 工具调用 sync/async 兜底 + 日志 |
| `bobanana/app.py` | 修改 | 装配 logging/skill/mcp；`load_agent_reach` |
| `bobanana/tui.py` | 修改 | `/skills /skill /mcp /load-agent-reach /debug` 命令 |
| `bobanana/__main__.py` | 修改 | `--debug`、`--load-agent-reach` 参数 |
| `requirements.txt` / `.env.example` / `mcp.json.example` | 修改/新增 | 依赖与配置模板 |
| `tests/test_skills_offline.py` | 新增 | 离线测 skill 注册与 web 工具签名 |

### 1.3 不在本次范围（明确不做）

- 不实现完整 MCP 服务端；不替 Agent-Reach 配置各平台 cookies/密钥（由用户提供）。
- 不做浏览器渲染抓取（fetch_url 只做静态 HTTP + 文本抽取）。
- 不改动既有变体 ReAct 主链逻辑（仅扩展工具与可观测性）。

### 1.4 依赖与前置条件

- 新增包：`langchain-mcp-adapters`、`mcp`、`ddgs`、`beautifulsoup4`（`httpx` 已装）。
- `git` 已可用（2.53）；Agent-Reach 各平台能力需其自身 CLI/cookies，属其文档范畴。
- 网页搜索/抓取需联网；离线下工具返回明确错误，不崩溃。

---

## 2. 目标逻辑链（阶段二对照 SSOT）

```
触发入口 → 输入校验 → 核心逻辑 → 持久化/副作用 → 返回/展示 → 失败与回滚
```

### 2.1 链路详述

| 环节 | 预期行为 | 关键文件/函数（计划） |
|------|----------|------------------------|
| 触发入口 | `--debug/--load-agent-reach` 标志；REPL `/skills /skill /mcp /load-agent-reach /debug`；任务执行时执行器调用新工具 | `__main__.py`, `tui.py`, `agents/executor.py` |
| 输入校验 | 技能名存在性校验；mcp.json 不存在/解析失败处理；URL/仓库地址非空；shell 首词白名单 | `skills/registry.py`, `mcp/client.py`, `tools/web_tools.py`, `tools/shell_tools.py` |
| 核心逻辑 | 扫描技能目录解析 front matter；加载 MCP 工具合并进 toolbox；web_search/fetch_url/clone_repo 执行 | `skills/registry.py`, `mcp/client.py`, `tools/web_tools.py`, `tools/registry.py` |
| 持久化/副作用 | 克隆库落 `<data_dir>/external/`；clone_repo 索引文件进结构化记忆；日志输出终端 | `app.py`, `tools/web_tools.py`, `logging_setup.py` |
| 返回/展示 | TUI 列技能/MCP 工具/日志；工具结果回灌执行器 | `tui.py`, `agents/executor.py` |
| 失败与回滚 | 缺依赖/无配置/连接失败/越界/超时→记日志+返回错误字符串，主链继续 | `mcp/client.py`, `tools/*`, `graph.py` |

### 2.2 验收标准（可观测）

- [ ] `import bobanana.app/graph/skills.registry/mcp.client/tools.web_tools` 全部成功。
- [ ] `--selfcheck` 新增 skills/mcp/web_tools 三项；离线下 skills 能发现本机 agent-reach 技能；mcp 无配置时报「skipped」；web 工具构建成功。
- [ ] 新增离线测试通过：技能注册 list/get、web 工具均存在于 toolbox。
- [ ] `--debug` 下能在终端看到节点与工具级日志。

### 2.3 风险与边界

| 场景 | 预期处理 |
|------|----------|
| 未装 langchain-mcp-adapters / 无 mcp.json | 记 info 日志，MCP 工具为空，继续 |
| MCP 服务器连接失败 | 捕获异常、记错误、该服务器跳过 |
| 无网络的 web_search/fetch_url | 返回 ERROR 字符串交回模型 |
| clone_repo 目标越界/已存在 | 限制在 workspace 内；已存在则 pull 或提示 |
| 异步 MCP 工具被同步执行 | 执行器先 sync 调用，失败回退 `asyncio.run(ainvoke)` |
| Agent-Reach 平台未配置 | 由其 CLI/SKILL 处理，本项目仅注册与转交 |

---

## 3. 实施记录（写代码过程中可追加）

| 时间 | 实际改动 | 与计划差异 |
|------|----------|------------|
| 2026-05-29 | 新增 `logging_setup.py`（RichHandler，级别可配，`set_level`） | 无 |
| 2026-05-29 | 新增 `skills/registry.py`（front-matter 解析、扫描、`clone_repo`） | 无 |
| 2026-05-29 | 新增 `mcp/client.py`（`McpManager`，asyncio 加载，缺依赖/无配置/失败均降级） | 无 |
| 2026-05-29 | 新增 `tools/web_tools.py`（web_search/fetch_url/clone_repo+索引到结构化记忆） | 无 |
| 2026-05-29 | 改 `tools/registry.py`（注册 skill/web/MCP 工具，共 10+ 个） | 无 |
| 2026-05-29 | 改 `shell_tools.py` 白名单加 agent-reach/mcporter/curl/gh/yt-dlp/rdt/twitter/xhs | 无 |
| 2026-05-29 | 改 `executor.py`（工具调用日志 + 异步 MCP 工具 `ainvoke` 兜底） | 无 |
| 2026-05-29 | 改 `config.py`（log_level/skill_dirs/mcp_config/agent_reach_repo/enable_web_tools/external_dir） | 无 |
| 2026-05-29 | 改 `graph.py`（节点级 INFO 日志、注入 skill/web/MCP 工具） | 无 |
| 2026-05-29 | 改 `app.py`（装配 logging/skills/mcp，`load_agent_reach`，扩充 selfcheck） | 无 |
| 2026-05-29 | 改 `tui.py`（`/skills /skill /mcp /load-agent-reach /debug`）与 `__main__.py`（`--debug/--load-agent-reach`） | 无 |
| 2026-05-29 | 新增 `tests/test_skills_offline.py`、`mcp.json.example`；更新 requirements/.env.example | 无 |
| 2026-05-29 | 修正 `clone_repo` 报告：按实际 SKILL.md 计数并说明同名去重 | 计划外修正，验证后发现报告不准 |
| 2026-05-29 | 用户已把 `.env.example` 改名为含真实 key 的 `.env`（gitignored），未改动其密钥 | 环境变化，遵守不碰密钥 |

---

## 4. 阶段二自查结论（交付前填写）

- [x] 入口与计划一致：`__main__`（`--debug/--load-agent-reach`）、TUI 五个新命令、执行器调用新工具——均存在且可达。
- [x] 数据流与计划一致：skills 扫描→`use_skill` 读指令→`run_shell` 调 CLI；MCP `mcp.json`→`asyncio.run(get_tools())`→并入 toolbox；web_search/fetch_url/clone_repo→（clone）索引进结构化记忆；日志贯穿节点与工具。
- [x] 分支与失败路径与计划一致：无 mcp.json→skipped；缺依赖→warning 降级；web 无网络→返回 ERROR 字符串（实测 DNS 被拒时优雅返回未崩溃）；clone 越界→拒绝；异步工具→`ainvoke` 兜底。
- [x] 验收标准已满足：导入 OK；`--selfcheck` 七项全 PASS（新增 skills 发现 agent-reach、mcp skipped、tools 10 个、graph 编译）；`test_graph_offline`、`test_skills_offline` 均 PASSED；`--debug` 终端可见节点/工具日志；git 实测成功克隆 Agent-Reach。

**偏差说明**（若无写「无」）：

- Agent-Reach 的 `SKILL.md` 名称为 `agent-reach`，与本机 `~/.agents/skills/agent-reach` 同名，按「先发现者优先」去重保留本机版本；功能不受影响，已在 `clone_repo` 返回信息中说明。
- 真实网页搜索结果需用户机的开放网络；本沙箱出站 DNS 受限（搜索端点 Query Refused），已验证为「优雅返回 ERROR」而非代码缺陷；git 出站正常，克隆已成功。
