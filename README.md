# 🍌 BoBanana 2.0 — 你的终端赛博猩猩

> **「代码写不完？让猩猩来。」**

一个纯终端 AI 编程 Agent，基于 LangChain + LangGraph 的变体 ReAct 工作流。  
你负责喝咖啡，它负责写代码、查文档、跑命令、修 bug。  
主 Agent 撸起袖子干，独立审查 Agent 在后面盯——干活有兜底，翻车不背锅。

当前版本：**3.0.0**（`multi-chat`，对，版本号跳得快——因为猩猩进化了 🧬）

---

## 🎯 这玩意能干啥？

| 能力 | 说明 |
|------|------|
| 🧠 **变体 ReAct 规划** | 计划 → 审查 → 执行 → 再审查，过不了就改，改完接着干 |
| 💬 **多窗口并发** | 同时跑多个任务，`/chat` 切窗口跟切浏览器标签一样顺滑 |
| 🧐 **意图感知** | 简单任务秒级响应，复杂任务自动加预算，不浪费 token |
| 🔍 **联网搜索+抓取** | 查文档、搜 StackOverflow、爬 API 手册——一条龙 |
| 🛠️ **MCP / 插件 / Shell** | 能接 MCP 服务器，能装自定义工具插件，跑命令？基操 |
| 🧩 **Skils 技能系统** | 内置交付质量门，代码写完自动审查，八荣八耻守门员 |
| 📦 **便携打包** | 解压即用，不用装 Python？它帮你装。不用配环境？它帮你配。 |
| 🧹 **会话 + 遗忘** | 超长对话自动摘要旧轮次，保持头脑清醒 |
| ↩️ **/undo 整轮回滚** | 翻车了？一键时光倒流，当作什么都没发生过 |
| ⏸️ **检查点续跑** | Ctrl+C 中断后 `/resume` 继续，不丢进度 |
| 🏠 **跨平台** | Windows / macOS / Linux，一个安装脚本走天下 |

---

## 🚀 一分钟跑起来

### 🥇 便携版（推荐 —— 懒人福音）

1. 下载或自己打一个 `dist/BoBanana2.0-portable.zip`
2. 解压，打开 `BoBanana2.0` 文件夹
3. **Windows**：双击 `install.cmd` 或 `安装.cmd`（给家里长辈准备的中文版）
4. **macOS / Linux**：
   ```bash
   chmod +x install.sh bb.sh
   ./install.sh
   ```
5. 按提示输入 API Key，完事。
6. 以后直接 `bb use` 启动（桌面上也有快捷方式）

### 🥈 开发者版（Git clone）

```bash
git clone https://github.com/ProfYangShengXu/BoBanana2.0.git
cd BoBanana2.0
python install.py
python -m bobanana --configure
./bb.sh start        # Mac/Linux
bb.cmd start         # Windows
```

### 🥉 硬核玩家（手动）

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填 API Key
python -m bobanana
```

详细的幼儿园级图文安装教程 👉 [INSTALL.md](INSTALL.md)

---

## ⚙️ 配置 API

猩猩需要吃饭——也就是 API Key。支持一切 OpenAI 兼容接口：

### 交互式配置（推荐）

```bash
python -m bobanana --configure
```

向导支持：**OpenAI**、**DeepSeek**、**Moonshot**、**Together**、**本地 Ollama**、自定义。

### 常见厂商一键配置

| 厂牌 | `OPENAI_BASE_URL` | `BOBANANA_MODEL` |
|------|-------------------|------------------|
| OpenAI | （留空） | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Moonshot | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| Ollama | `http://127.0.0.1:11434/v1` | `llama3` |

> ⚠️ `.env` 在 `.gitignore` 里，不会上传 GitHub，放心填。

---

## 🎮 日常命令

| 操作 | Windows | Mac/Linux |
|------|---------|-----------|
| 启动 | `bb.cmd start` | `./bb.sh start` |
| 快速启动 | `bb.cmd use` | `./bb.sh use` |
| 改 API | `bb.cmd config` | `./bb.sh config` |
| 自检 | `python -m bobanana --selfcheck` |
| 测试 | `bb.cmd test` / `pytest` |
| 打包便携版 | `.\pack.ps1` |

进终端后 `/help` 看完整命令列表。

### 💬 多窗口操作（3.0 重点）

| 命令 | 说明 |
|------|------|
| `/chat new [标题]` | 新开一个窗口干活 |
| `/chat switch <id\|#>` | 切过去瞅一眼 |
| `/chat kill <id>` | 关掉不想要的窗口 |
| `/history [n]` | 翻旧账（最近 n 轮） |
| `/forget` | 猩猩健忘，手动压缩记忆 |
| `/undo` | 时光倒流，当没发生过 |

提示符上会显示 `[窗口id|tok:已用token]`，Tab 补全 slash 命令。

---

## 🧩 内置 Skills

猩猩随身带两个看家本领（便携版已包含，无需额外安装）：

| Skill | 用途 |
|-------|------|
| `code-delivery-gate` | 代码交付质量门 —— 八荣八耻，写完自动审查，拒绝屎山 |
| `agent-reach` | 多平台搜索 / 抓取 —— 没有猩猩找不到的东西 |

---

## 🔧 高级定制

想调教猩猩？改 `.env` 就行：

| 环境变量 | 干啥的 | 默认值 |
|----------|--------|--------|
| `BOBANANA_MAX_STEPS` | 一步最多整多少步 | 20 |
| `BOBANANA_MAX_TOOL_ITERS` | 每步调工具上限 | 24 |
| `BOBANANA_SHELL_TIMEOUT` | 跑命令超时（秒） | 120 |
| `BOBANANA_ENABLE_DELIVERY_GATE` | 要不要质量门 | true |
| `BOBANANA_ENABLE_CHECKPOINTS` | 要不要检查点 | true |
| `BOBANANA_WORKSPACE` | 工作区路径 | 当前目录 |

完整列表见 [`.env.example`](.env.example)

---

## 🛠️ 开发

```bash
pytest                  # 离线跑（默认不调 LLM）
pytest -m live          # 真 LLM 测试（需要 API Key）
python -m bobanana --debug
```

---

## 🧠 架构一句话

主 Agent（规划师+执行器） ↔ 独立审查 Agent（盯梢的） ↔ 工具层（文件/Shell/Web/MCP/插件） ↔ 记忆层（工作记忆+SQLite+缓存）

每轮计划先审查再过，审查不过就改，改完再审——猩猩虽莽，但很怂。

详见 [docs/PROJECT.md](docs/PROJECT.md)

---

## 📜 许可证

MIT —— [LICENSE](LICENSE) 里有全部法律废话。

---

## 🙈 为什么叫 BoBanana？

因为谐音 **「剥香蕉」** ——  
猴子剥香蕉，猩猩写代码。  
你不会想知道为什么版本号从 2.0 跳到 3.0 的——  
只能说，那只猩猩当年把 2.0 的代码吃完之后……进化了 🧬🍌

---

<p align="center">
  <sub>⚠️ 猩猩正在搬运中 · 如果看到它蹲在树上发呆 · 请耐心等待</sub>
</p>
