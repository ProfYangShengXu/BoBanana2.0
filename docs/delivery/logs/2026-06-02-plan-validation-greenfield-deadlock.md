# 2026-06-02 — 计划校验 / pytest 绿场死锁修复

## 问题（6.1-3）

在空工作区（AIwiki）上：
- 计划引用将 **创建** 的路径（`docs/design/…`、`tests/…`）被判 `unknown_paths` → G1 永不 execute
- 「分析知识点」误触发 BoBanana **架构批判** 规则（要求 `bobanana/`、`tests/`、`docs/delivery/output/`）
- 无测试套件时仍要求先 `pytest --collect-only` 才能 `write_file` 交付物

## 改动

- `plan_validation`：`is_bobanana_repo_workspace`、`_step_plans_to_create_path`（含 **编写/写入** 自然语言）、`greenfield`/`is_sparse_workspace_index`、路径 token 去中文粘连、收窄 `is_architecture_task`
- `report_validation`：`workspace_has_test_suite`；无 tests 时跳过 pytest 写门禁
- `graph` / `registry`：绿场交付步不要求 pytest collect
- **绿场** `unknown_paths` 整表清空；禁止计划去读尚不存在的文件
- `workspace_map` / `planner` / `reviewer`：区分 BoBanana 自审 vs 新建项目，避免误注入 `docs/delivery/output/` 规则

## 验证

`pytest tests/test_features.py -k "greenfield or chinese_suffix or wiki_feature or deliverable_write_not_blocked"`

## 续修（6.1-4 绿场读步骤未拦截）

根因两处：

1. `_step_plans_to_create_path` 中 `\bmd ` 误匹配 `docs/PROJECT.md` 里的 `.md `，把 **read** 当成 **mkdir 创建**，绿场读校验被 `continue` 跳过。
2. `_path_in_index` 在「父目录存在」时返回 True（仅有 `docs/` 无 `PROJECT.md` 也算在盘），读缺失文件未报错。

修复：`(?<!\.)md\s+` + 将 `read_file` 判定提前；`_path_in_index` 仅 `is_file`/`is_dir`。新增单测 3 条。

## 自查结论

- 入口 `validate_plan` → 绿场分支读步骤 → `_step_plans_to_create_path` / `_path_in_index`
- `pytest tests/` 235 passed；`python -m bobanana --selfcheck` PASS

## 续修 2（路径判定 / phantom / 架构 ok）

| 问题 | 修复 |
|------|------|
| `read_file …了解实现` 因 `_STEP_OUTPUT_MARKERS` 含「实现」被判创建 | `_step_op_reads_path` 优先；输出标记需 `_path_mentioned_in_step` |
| 绿场 `write_file package.json` 误触 BoBanana phantom | `_check_phantom` 仅在 `bobanana_repo` 或绿场外生效 |
| `_reads_blocked_delivery_md` 中「分析」误伤含分析的写步骤 | 读判定改为工具/读取动词，去掉裸「分析」 |
| 架构任务缺 `write_file` 仅 warning 不置 `ok=False` | 补 `v.ok = False` |

`pytest tests/` 237 passed；selfcheck PASS。

## 续修 3（6.1-4 根因：`.bobanana` 误判为 BoBanana 仓库）

| 问题 | 修复 |
|------|------|
| Live index 含 `.bobanana/tools` 时 `"bobanana/" in idx` 为真 | `is_bobanana_repo_workspace` 用 `(?<!\.)bobanana/` + 磁盘上 `bobanana/graph.py` |
| AIwiki 注入 `WORKSPACE_MAP` 而非 `GREENFIELD_MAP`，规划器偏向 `bobanana/*.py` | 同上；`inject_workspace_context` 恢复绿场提示 |
| `编写软件设计文档 docs/…` 动词与路径不相邻 | `_step_explicit_write_path` 允许中间 ≤64 字中文说明 |

单测：`test_bobanana_repo_not_confused_with_dot_bobanana_in_index` 等。`pytest` 239 passed。
