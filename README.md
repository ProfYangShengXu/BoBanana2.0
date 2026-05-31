# BoBanana 2.0

**纯终端编程 Agent** — 基于 LangChain + LangGraph 的变体 ReAct 工作流：主 Agent 规划与执行，独立审查 Agent 逐步把关，支持动态预算、检查点续跑、技能扩展与交付质量门。

当前版本：**3.0.0**（`multi-chat`）

---

## 快速开始

### 环境要求

- **Python 3.10+**（Windows 安装时勾选 *Add Python to PATH*）
- **OpenAI 兼容 API Key**（OpenAI / DeepSeek / Moonshot / 本地 Ollama 等）

### 方式一：下载便携包（推荐新用户）

1. 下载或自行打包 `dist/BoBanana2.0-portable.zip`（开发者执行 `.\pack.ps1`）
2. 解压，打开 **`BoBanana2.0`** 文件夹
3. **Windows**：双击 `install.cmd` 或 `安装.cmd`
4. **macOS / Linux**：
   ```bash
   chmod +x install.sh bb.sh
   ./install.sh
   ```
5. 按提示配置 API Key，完成后双击桌面快捷方式或运行 `bb use`

> 详细图文教程：[INSTALL.md](INSTALL.md)（幼儿园级分步说明）

### 方式二：克隆仓库（开发者）

```bash
git clone https://github.com/ProfYangShengXu/BoBanana2.0.git
cd BoBanana2.0
python install.py          # 或 python3 install.py
# 配置 API
python -m bobanana --configure
# 启动
./bb.sh start              # macOS/Linux
# 或 Windows:
bb.cmd start
```

### 方式三：手动安装

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Unix:     source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env     # Windows
cp .env.example .env       # macOS/Linux
python -m bobanana --configure
python -m bobanana
```

---

## 配置 API

### 交互配置（推荐）

| 平台 | 命令 |
|------|------|
| Windows | `bb.cmd config` |
| macOS / Linux | `./bb.sh config` |
| 通用 | `python -m bobanana --configure` |

向导支持：**OpenAI**、**DeepSeek**、**Moonshot**、**Together**、**本地 OpenAI 兼容**、自定义。

### 手动编辑 `.env`

复制 `.env.example` 为 `.env` 后修改：

```env
# 必填 — 联网执行任务
OPENAI_API_KEY=sk-your-key-here

# 可选 — DeepSeek / Moonshot / 本地服务 必填 Base URL
OPENAI_BASE_URL=https://api.deepseek.com/v1

# 模型名
BOBANANA_MODEL=deepseek-chat
# 或 OpenAI: gpt-4o-mini
```

### 常用提供商对照

| 提供商 | `OPENAI_BASE_URL` | `BOBANANA_MODEL` 示例 |
|--------|-------------------|------------------------|
| OpenAI | （留空） | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Moonshot | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| Ollama 本地 | `http://127.0.0.1:11434/v1` | `llama3` |

### 非交互安装时传入 Key

```powershell
.\install.ps1 -ApiKey sk-xxx -BaseUrl https://api.deepseek.com/v1 -Model deepseek-chat
```

```bash
python3 install.py --api-key sk-xxx --base-url https://api.deepseek.com/v1 --model deepseek-chat
```

> **安全提示**：`.env` 已在 `.gitignore` 中，切勿提交到 GitHub。

---

## 日常命令

| 操作 | Windows | macOS / Linux |
|------|---------|---------------|
| 启动（含测试） | `bb.cmd start` | `./bb.sh start` |
| 快速启动 | `bb.cmd use` | `./bb.sh use` |
| 改 API | `bb.cmd config` | `./bb.sh config` |
| 离线自检 | `python -m bobanana --selfcheck` | 同左 |
| 运行测试 | `bb.cmd test` / `pytest` | `./bb.sh test` |
| 打便携包 | `.\pack.ps1` | — |

终端内输入 `/help` 查看 REPL 命令。

**3.0 多窗口**：`/chat new|list|switch|kill|rename|delete` — 后台并发任务；提示符显示 `[窗口id|tok:累计]`；Tab 补全 slash 命令；`/undo` 整轮撤销。

| 命令 | 说明 |
|------|------|
| `/chat new [标题]` | 新建对话窗口 |
| `/chat switch <id\|#>` | 跳转并回放最近输出 |
| `/undo` | 撤销当前窗口最近一轮（文件+记忆） |

---

## 内置 Skills

便携包自带 `skills/` 目录（无需额外安装 Cursor skills）：

| Skill | 用途 |
|-------|------|
| `code-delivery-gate` | 代码任务交付质量门 |
| `agent-reach` | 多平台搜索 / 抓取路由 |

更新 skills 后重新打包：

```powershell
.\scripts\bundle-skills.ps1
.\pack.ps1
```

---

## 主要能力

- **变体 ReAct**：plan → 审查 → execute → 审查，未通过则修订
- **多对话窗口（3.0）**：后台任务池并发；每窗口独立 memory/graph/Sqlite 检查点；`/chat` 跳转
- **Intent 层**：自动评估任务难度，动态缩放步数预算（3.0 已移除工具次数硬上限）
- **重复工具微规划**：同一工具签名 ≥3 次触发无审查 `micro_replan`
- **多轮规划**：directive 满足后可进入下一轮 plan（`BOBANANA_MAX_PLAN_ROUNDS`）
- **Token 统计**：提示符与 session 元数据累计 in/out tokens
- **整轮 /undo**：文件快照 + 记忆 + turns.jsonl 回滚
- **证据驱动审查**：审查器依据真实 `write_file` / `run_shell` 输出，而非 Agent 自述
- **指令门**：`key_directives` 未满足不结束任务
- **检查点**：Ctrl-C 中断后可 `/resume` 或 `/rollback`
- **工具**：读写文件、受控 Shell、web 搜索/抓取、Git 克隆、MCP、插件
- **记忆**：工作记忆 + SQLite 结构化记忆 + 探索缓存

架构与运维详见 [docs/PROJECT.md](docs/PROJECT.md)。

---

## 高级配置

完整环境变量见 [`.env.example`](.env.example)。常用项：

| 变量 | 说明 | 默认 |
|------|------|------|
| `BOBANANA_MAX_STEPS` | 任务最大步数（天花板） | 20 |
| `BOBANANA_MAX_TOOL_ITERS` | 每步工具调用上限 | 24 |
| `BOBANANA_SHELL_TIMEOUT` | Shell 超时（秒） | 120 |
| `BOBANANA_ENABLE_DELIVERY_GATE` | 代码任务注入交付门 | true |
| `BOBANANA_ENABLE_CHECKPOINTS` | 启用检查点 | true |
| `BOBANANA_WORKSPACE` | Agent 工作区根目录 | 当前目录 |

无 API Key 时仍可运行 `--selfcheck` 与离线测试；联网任务需配置 Key。

---

## 开发

```bash
pytest                  # 离线测试（默认排除 live）
pytest -m live          # 真实 LLM 验收（需 OPENAI_API_KEY）
python -m bobanana --debug
```

---

## 许可证

MIT — 见 [LICENSE](LICENSE)（如未包含则默认可自行添加）。

---

<details>
<summary><strong>English summary (click to expand)</strong></summary>

BoBanana 2.0 is a terminal coding agent using LangGraph variant-ReAct: planner + reviewer loops, intent-based budget scaling, evidence-grounded review, checkpoints, skills/MCP/web tools, and an optional delivery-gate skill for code tasks.

See [INSTALL.md](INSTALL.md) for the full install guide and [.env.example](.env.example) for configuration.

</details>
