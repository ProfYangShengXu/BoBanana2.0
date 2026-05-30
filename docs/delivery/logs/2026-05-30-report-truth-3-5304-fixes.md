# 更新日志：report-truth 3（5.30-4 回归修复）

**版本目标**：2.1.3 (`report-truth-3`)

## 1. 目标

修复 5.30-4 暴露的校验缺口：FALSE_CLAIM 漏网、needs_web 与 fetch_url 不联动、测试数无 pytest 证据、gate/finalize 矛盾、agent 读 stale .md 作 ground truth。

## 2. 逻辑链

```
P0 report_validation: 扩充 FALSE_CLAIM + URL 消 needs_web + 分层 critical/minor
P1 registry: pytest --collect-only 写 scratch；blocked md read（critique_report / 其他 output）
P1 graph execute: 写步强制 pytest 提示
P1 graph advance/gate/finalize: minor-only → soft-pass / 补救步 / status 对齐
P2 registry._read: is_blocked_md_read 拦截未验证 .md
```

## 3. 涉及文件

- `bobanana/report_validation.py`
- `bobanana/tools/registry.py`
- `bobanana/graph.py`
- `bobanana/agents/executor.py`
- `bobanana/version.py`, `VERSION`, `docs/PROJECT.md`
- `tests/test_features.py`

## 4. 自查结论

- P0：`FALSE_CLAIM` 覆盖 Chroma/memory.store/_create_graph/config shell_timeout；`pypi.org/project/pytest-cov` 清除 needs_web；同行否定语境跳过误报。
- P1：`pytest --collect-only` 写 scratch + 测试数校验；gate 不可 acceptable 时追加 `[补救/报告校验]`；finalize 用 `validation_acceptable_ok` 对齐 status。
- P2：`is_blocked_md_read` 拦截 critique_report 与其他 delivery output .md。
- 测试：pytest 全绿；selfcheck PASS。
