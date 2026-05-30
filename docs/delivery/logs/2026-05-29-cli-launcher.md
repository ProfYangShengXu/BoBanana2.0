# 更新日志 — 2026-05-29 · cli-launcher

> **关联任务**：集成终端指令，简化为「启动-使用-关闭-重启」四个动作，且「启动」附带测试。
> **状态**：实施中

---

## 1. 计划

### 1.1 目标
- [ ] 一个统一入口脚本提供四个动词：`start`（跑测试通过后再启动）、`use`（快速启动不测）、`close`（停止运行中的实例）、`restart`（close+start）。
- [ ] `start` 自动确保 venv/依赖就绪，并先跑 `--selfcheck` + 两个离线测试，全过才启动。
- [ ] Windows PowerShell 为主，附带 `.cmd` 包装免去 ExecutionPolicy 烦恼。

### 1.2 改动范围
| 路径 | 动作 | 说明 |
|------|------|------|
| `bb.ps1` | 新增 | 主启动器（start/use/close/restart/test/setup/help） |
| `bb.cmd` | 新增 | cmd/双击包装，转调 bb.ps1（Bypass 执行策略） |
| `README.md` / `docs/PROJECT.md` | 修改 | 增加简化命令用法 |

### 1.3 不做
- 不改 Python agent 本体逻辑；不做后台守护进程。

### 1.4 依赖
- 复用现有 `.venv` 与 `requirements.txt`；测试用 `BOBANANA_EMBEDDING_PROVIDER=local` 离线跑。

---

## 2. 目标逻辑链（SSOT）

| 环节 | 预期行为 | 关键文件/函数 |
|------|----------|----------------|
| 触发入口 | `bb <verb> [args]` | `bb.cmd` → `bb.ps1` 的 switch |
| 输入校验 | 未知 verb → 打印帮助；venv 缺失 → 自建 | `bb.ps1: Ensure-Venv` |
| 核心逻辑 | start=测试→启动；use=启动；close=按命令行匹配停进程；restart=close+start | `bb.ps1: Run-Tests/Start-Agent/Stop-Bobanana` |
| 持久化/副作用 | 启动前端 REPL；测试期临时设 local 嵌入后还原 | `bb.ps1` |
| 返回/展示 | 彩色 `[bb] …` 提示；测试失败即中止启动 | `bb.ps1` |
| 失败与回滚 | 测试非零退出→throw 中止，不启动；无运行实例→提示 | `bb.ps1` |

### 2.2 验收
- [ ] `bb test` 全绿；`bb close` 无实例时友好提示；`bb help` 列出四动词。
- [ ] `bb start` 在测试通过后进入 REPL（交互，手动验证）。

---

## 3. 实施记录
| 时间 | 改动 | 差异 |
|------|------|------|
| 2026-05-29 | 新增 `bb.ps1`（start/use/close/restart/test/setup/help）+ `bb.cmd` 包装 | — |
| 2026-05-29 | Run-Tests 期间临时设 `BOBANANA_EMBEDDING_PROVIDER=local` 并在 finally 还原 | 计划内细化，避免污染用户配置 |

---

## 4. 阶段二自查结论
- [x] 入口/数据流/分支与计划一致：`bb.cmd`→`bb.ps1` switch；start=Ensure-Venv→Run-Tests→Start-Agent；use=Ensure-Venv→Start-Agent；close=Stop-Bobanana（按命令行匹配、排除自身）；restart=close→测试→启动。
- [x] 验收满足：`bb help` 列出四动词；`bb test` 全绿（selfcheck + 两个离线测试，exit 0）；`bb close` 无实例时友好提示。`start/use` 进入交互式 REPL 需手动体验，底层即已验证的 `python -m bobanana`。

**偏差说明**：无。（`start/use` 为前台交互 REPL，故 `close/restart` 主要面向后台/另一终端遗留的实例；测试期对嵌入 provider 的临时改写已用 try/finally 还原，不影响用户 `.env`。）
