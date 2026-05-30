# 复制到 Cursor User Rules（全局每对话生效）

**路径**：`Cursor Settings` → `Rules` → `User Rules` → 粘贴下方全文 → 保存。

```
【强制】每个 Agent 对话遵循 skill code-delivery-gate（%USERPROFILE%\.cursor\skills\code-delivery-gate\）。一旦涉及写/改代码或声称「已完成」：

0. 写代码前：在 docs/delivery/logs/YYYY-MM-DD-<任务>.md 写计划改动与目标逻辑链（阶段二对照 SSOT）；模板见 templates/UPDATE-LOG-TEMPLATE.md。
1. 交付前：清理改动区多余代码。
2. 写完后：对照更新日志 §2 严肃自查逻辑链路与用户负担；回填日志 §4 自查结论。
3. 交付前：执行 ops/RUNBOOK.md 运维自检。
4. 全部完成后：按 templates/PROJECT-DOC-TEMPLATE.md 与 example.md 风格更新 docs/PROJECT.md。

纯问答、未改代码可不跑构建；改代码则阶段零～四不可跳过（hotfix 须补录日志）。交付摘要用 SKILL.md 模板。

提醒：首次适用时回复最前写「[code-delivery-gate] 已启用」；摘要首行写「已执行」及阶段 ✓。同对话不重复启用提醒。
```
