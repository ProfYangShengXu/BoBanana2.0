# 更新日志 — 2026-05-30 · 工具插件体系 + 权限 + semver + 可发现性

> **状态**：已完成（54 离线用例通过；selfcheck 加载 2 个示例插件）

## 实施摘要
| 能力 | 实现 |
|------|------|
| `.bobanana/tools/` drop-in | `seed_plugin_directory` + `PluginLoader.scan()` |
| YAML manifest | `handler: echo` / `handler: shell`，semver + permissions |
| 装饰器 | `@register_tool` in `*.py` plugins |
| semver | 核心 `1.0.0`；插件 YAML/装饰器声明，校验 MAJOR.MINOR.PATCH |
| 权限 | `read/write/shell/network/admin` + `BOBANANA_TOOL_PERMISSIONS` |
| Agent 内省 | `describe_tool_registry` 工具 + `/tools` + selfcheck |
| 热加载 | `/reload-tools` |

## 验收
- [x] 54 pytest passed
- [x] selfcheck: `plugins_loaded=2`, `describe_tool_registry` present
- [x] 权限不足 write → ERROR
