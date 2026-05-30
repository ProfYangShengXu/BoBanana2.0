# BoBanana 2.0 — 安装教程（幼儿园级 · 一步一步来）

> 不用懂编程。照着做就行。  
> 支持 **Windows 10/11**、**macOS**、**Linux**。

---

## 第 0 步：你需要准备什么？

| 东西 | 是什么 | 怎么弄 |
|------|--------|--------|
| **电脑** | 能上网的普通电脑 | 你已经有了 ✓ |
| **Python 3.10+** | 运行 BoBanana 的「引擎」 | 见下方「装 Python」 |
| **API Key** | 大模型账号的密码（像游戏 CDKey） | OpenAI / DeepSeek 等网站申请；**可以稍后再填** |
| **BoBanana 文件夹或 zip** | 本软件 | 解压或复制到任意目录 |

---

## 第 1 步：安装 Python（只做一次）

### Windows

1. 打开浏览器，访问：https://www.python.org/downloads/
2. 点黄色大按钮 **Download Python 3.x.x**
3. 双击下载的安装包
4. **最重要**：第一页底部勾选 **`Add python.exe to PATH`**（打勾！）
5. 点 **Install Now**，等进度条走完
6. 怎么知道成功了？  
   - 按 `Win + R`，输入 `cmd`，回车  
   - 黑窗口里输入：`python --version`  
   - 看到 `Python 3.10` 或更高 → **成功** ✓

### macOS

1. 打开「终端」（Spotlight 搜 Terminal）
2. 如果已装 Homebrew，输入：
   ```bash
   brew install python@3.12
   ```
3. 验证：`python3 --version` 显示 3.10+ → **成功** ✓

### Linux（Ubuntu / Debian 举例）

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
python3 --version
```

看到 3.10+ → **成功** ✓

---

## 第 2 步：拿到 BoBanana 文件夹

### 方式 A：别人给你的 zip（最常见）

1. 把 `BoBanana2.0-portable.zip` 拷到电脑
2. **右键 → 解压** 到任意位置
3. 打开解压出来的 **`BoBanana2.0`** 文件夹（不是只停留在 zip 图标上）
4. 里面应有：**`install.cmd`**、**`安装.cmd`**、**`START-HERE.txt`**、**`INSTALL.md`**
   - 若看不到：先打开 `START-HERE.txt`；Windows 资源管理器 → 查看 → 勾选「文件扩展名」

### 方式 B：开发者自己打包

在项目根目录（Windows PowerShell）：

```powershell
.\pack.ps1
```

会在 `dist\BoBanana2.0-portable.zip` 生成可分发包（**不含**你的 `.env` 密钥和 `.venv`）。

---

## 第 3 步：运行安装程序（核心，只做一次）

### Windows — 最简单

1. 进入解压后的 **`BoBanana2.0`** 文件夹
2. **双击 `install.cmd`** 或 **`安装.cmd`**（两个相同）
3. 黑色/蓝色窗口会依次问你要不要配 API —— 见下一节
4. 最后窗口写 **`[install] 安装完成`** → **成功** ✓
5. 桌面会出现 **「BoBanana 2.0」** 图标（可双击启动）

### macOS / Linux

1. 打开终端，`cd` 进 BoBanana 文件夹：
   ```bash
   cd ~/BoBanana2.0          # 改成你的实际路径
   chmod +x install.sh bb.sh   # 只需第一次
   ./install.sh
   ```
2. 按提示配置 API（可跳过）
3. 看到 **`[install] 安装完成`** → **成功** ✓

### 任何系统 — 用 Python 直接装

```bash
cd /path/to/BoBanana2.0
python3 install.py
```

---

## 第 4 步：配置 API Key（联网对话必做）

安装过程中会问你；**也可以随时再改**。

### 交互配置（推荐，会一步步问）

| 系统 | 命令 |
|------|------|
| Windows | `.\bb.cmd config` |
| Mac/Linux | `./bb.sh config` |
| 通用 | `python -m bobanana --configure` |

你会看到：

1. **选提供商**（1=OpenAI，2=DeepSeek，3=Moonshot …）
2. **粘贴 API Key**（输入时屏幕不显示，正常的）
3. **Base URL**（OpenAI 直接回车；DeepSeek 会自动填好）
4. **模型名**（直接回车用默认）

### 手动改文件

用记事本 / VS Code 打开项目根目录的 **`.env`**：

```env
OPENAI_API_KEY=sk-你的密钥
OPENAI_BASE_URL=https://api.deepseek.com/v1   # DeepSeek 必填；OpenAI 可删此行
BOBANANA_MODEL=deepseek-chat                  # 或 gpt-4o-mini 等
```

> `.env` **只在你本机**，不会被打进 zip 包。

### 常用提供商对照表

| 提供商 | OPENAI_BASE_URL | BOBANANA_MODEL 示例 |
|--------|-----------------|---------------------|
| OpenAI | （留空） | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Moonshot | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| 本地 Ollama | `http://127.0.0.1:11434/v1` | `llama3` |

### 非交互安装（给 IT / 脚本用）

```powershell
# Windows
.\install.ps1 -ApiKey "sk-xxx" -BaseUrl "https://api.deepseek.com/v1" -Model "deepseek-chat"
```

```bash
# macOS / Linux
python3 install.py --api-key sk-xxx --base-url https://api.deepseek.com/v1 --model deepseek-chat
```

暂时不配 Key（纯离线自检）：

```bash
python3 install.py --skip-api-key
```

---

## 第 5 步：第一次启动

| 你想… | Windows | macOS / Linux |
|--------|---------|---------------|
| 稳妥启动（先跑测试） | 双击桌面图标，或 `.\bb.cmd start` | `./bb.sh start` |
| 快速启动 | `.\bb.cmd use` | `./bb.sh use` |
| 只检查能不能用 | `.\bb.cmd test` | `./bb.sh test` |

成功标志：出现 **`bobanana>`** 提示符。输入 `/help` 看命令列表。

---

## 第 6 步：怎么知道装对了？（验收清单）

请逐项打勾：

- [ ] `python --version` 或 `python3 --version` ≥ 3.10
- [ ] 文件夹里有 `.venv` 目录（安装后自动出现）
- [ ] 运行 `python -m bobanana --selfcheck` 全部 **PASS**
- [ ] `.env` 里已填 `OPENAI_API_KEY`（若要联网做任务）
- [ ] `bobanana>` 能输入 `/help` 并看到帮助

---

## 常见问题（照着排查）

### 「找不到 python / python3」

→ Python 没装，或 Windows 没勾选 **Add to PATH**。重装 Python 并打勾。

### 「pip install failed」

→ 检查网络；公司网络可能需要代理。可试：`python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`

### 安装成功但 Agent 不回答

→ 多半没配 API Key。运行 `bb config` 或编辑 `.env`。

### DeepSeek 报 404 / 连接错误

→ 确认 `OPENAI_BASE_URL=https://api.deepseek.com/v1`（末尾要有 `/v1`）。

### macOS 提示「无法打开 install.sh」

→ 终端里执行：`chmod +x install.sh bb.sh`，再用 `./install.sh`。

### Windows 双击 install.cmd 闪退

→ 右键 install.cmd → **以管理员身份运行** 不一定需要；更常见是缺 Python。用 cmd 手动 `cd` 到目录再运行 `install.cmd` 看红色报错。

---

## 日常命令速查

| 操作 | Windows | macOS / Linux |
|------|---------|---------------|
| 安装 / 重装依赖 | `install.cmd` | `./install.sh` |
| 改 API | `.\bb.cmd config` | `./bb.sh config` |
| 启动（带测试） | `.\bb.cmd start` | `./bb.sh start` |
| 快速启动 | `.\bb.cmd use` | `./bb.sh use` |
| 关闭 Agent | `.\bb.cmd close` | `./bb.sh close` |
| 离线自检 | `python -m bobanana --selfcheck` | 同左 |

---

## 换电脑 / 卸载

**迁移到新电脑：**

1. 复制整个文件夹（或重新解压 zip）
2. **不要**复制别人的 `.venv`（在新电脑重新 `install`）
3. **可以**复制 `.env`（里面有你的 Key）
4. 新电脑再跑一遍安装程序

**卸载：**

- 直接删除整个 BoBanana 文件夹
- Windows 可选：`.\install.ps1 -Uninstall` 只删桌面快捷方式

---

## 更多说明

- 功能与架构：`docs/PROJECT.md`
- 英文速览：`README.md`
- 全部配置项：`.env.example`
