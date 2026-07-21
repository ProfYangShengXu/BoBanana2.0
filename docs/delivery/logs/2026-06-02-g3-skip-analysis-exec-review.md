# 2026-06-02 — G3 skip_analysis_exec_review

## 改动

- `bobanana/step_classify.py`：`is_analysis_only_step`（描述 + `step_touches` + `last_evidence`）
- `Settings.skip_analysis_exec_review` / `BOBANANA_SKIP_ANALYSIS_EXEC_REVIEW`（默认 True）
- `_exec_review_node`：分析只读步合成 `approved=True`，不调用 `reviewer.review_artifact`，事件 `skipped=True`
- TUI：`exec_review skipped (analysis-only / G3)`

## 验证

`pytest tests/` — `test_is_analysis_only_*`、`test_exec_review_skips_llm_for_analysis_only`
