# 更新日志 — 2026-05-30 · workspace-memory-isolation

> **关联任务**：修复切换工作区时记忆串用（结构化事实 / scratch 索引 / 旧 graph 仍引用旧 memory）。
> **状态**：已完成

## 根因

1. `set_workspace` 虽重建 `MemoryManager`，但若 `_graph` 未置空或仍被复用，executor/toolbox 继续指向旧 workspace 与旧 memory。
2. `skill_dirs` 在切换时不断 append 旧工作区路径，易造成技能扫描混乱（非主因，但已修正）。
3. `prepare_workspace` 仅看 `workspace_index` scratch 是否存在，未校验 `workspace_root`，异常路径下可能复用上一工作区的索引文本。

## 改动

- `config.resolve_data_dir` / `default_skill_dirs`：统一 data_dir 与 skill 路径解析。
- `app.set_workspace`：按新 workspace 解析 data_dir、重置 skill_dirs、重载 MCP、清空 `_applied_budget`。
- `app._ensure_graph`：检测 memory/workspace 与当前 settings 不一致时强制重建 graph。
- `graph._prepare_workspace_node`：`workspace_root` 不匹配时清空 scratch 再建索引。
- `MemoryManager(..., workspace=)`：绑定 `workspace_root` 到 scratch。
- 回归测试 3 项（`test_features.py`）。

## 自查

- [x] `pytest` 107 passed（offline）
