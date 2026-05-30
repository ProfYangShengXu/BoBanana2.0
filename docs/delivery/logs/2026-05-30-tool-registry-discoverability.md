# 更新日志 — 2026-05-30 · 工具注册表可发现性修复

> **关联任务**：agent 自检误报「工具注册机制完全缺失」——实际查了不存在的 `.bobanana/tools/`，未读 `bobanana/tools/registry.py`。
> **状态**：已完成

## 3. 实施记录
| 时间 | 改动 | 差异 |
|------|------|------|
| 2026-05-30 | Toolbox.catalog() + REGISTRY_MODULE 常量 | 按计划 |
| 2026-05-30 | app.list_tools()；selfcheck 报告 registry/sources | 按计划 |
| 2026-05-30 | tui /tools + HELP | 按计划 |
| 2026-05-30 | PROJECT.md 工具架构节（纠正 .bobanana/tools 误解） | 按计划 |

## 4. 阶段二自查结论
- [x] `/tools` 与 selfcheck 均指向 `bobanana.tools.registry.Toolbox`
- [x] pytest 49 passed（+2）；selfcheck tools 行含 registry/sources/read_ok

## 1. 计划
| 路径 | 动作 | 说明 |
|------|------|------|
| `bobanana/tools/registry.py` | 修改 | 新增 `Toolbox.catalog()` 返回 name/description/source |
| `bobanana/app.py` | 修改 | `list_tools()` 门面；selfcheck 报告 registry 路径与来源统计 |
| `bobanana/tui.py` | 修改 | `/tools` 命令 + HELP |
| `tests/test_features.py` | 修改 | catalog 与 selfcheck 格式断言 |
| `docs/PROJECT.md` | 修改 | 明确工具注册架构（纠正 `.bobanana/tools` 误解） |

## 2. 目标逻辑链
入口 `/tools` 或 `--selfcheck` → `Application.list_tools()` / selfcheck → `Toolbox.catalog()` → 列出 StructuredTool 元数据（非扫 `.bobanana/tools` 目录）。

## 3. 验收
- [ ] catalog 含 core 四件套 + 可选 skill/web/mcp
- [ ] selfcheck tools 行含 `registry=` 与 `sources=`
- [ ] `/tools` 可列出
- [ ] pytest 通过
