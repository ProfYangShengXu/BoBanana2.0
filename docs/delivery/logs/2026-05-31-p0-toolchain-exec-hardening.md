# P0 工具链 + 执行层加固

> 背景：见本对话「批判工具链和执行层」分析。本次落地 P0 五项：A1 edit_file、A2 read_file 续读、A3 run_shell 保尾、B1 重复 ERROR 断路、B2 invoke 兜底。

## §1 计划更新

**目标**：消灭近期反复踩的三个坑（空转、崩溃、验证假阴），并降低整文件重写的 token/丢码风险。

| # | 改动 | 文件 | 说明 |
|---|------|------|------|
| A1 | 新增 `edit_file` 工具 | `tools/file_tools.py`、`tools/registry.py` | search-replace 精确改文件，唯一匹配校验；走 journal 快照 + 缓存失效 + memory 记录，与 write_file 一致 |
| A2 | `read_file` 加 `offset`/`limit` | `tools/file_tools.py`、`tools/registry.py` | 行级续读；缓存 key 含 offset/limit；截断时提示续读 |
| A3 | `run_shell` 截断改 head+tail | `tools/shell_tools.py` | 保留开头 + 结尾，避免 pytest/build 的结尾汇总被吃掉 |
| B1 | 重复 ERROR 签名计入断路 | `agents/executor.py` | 同一 ERROR 签名重复 ≥2 次即触发 MICRO_REPLAN，不再等 stall_cap=20 |
| B2 | 包裹 LLM invoke 异常兜底 | `agents/executor.py` | invoke 异常有限重试，最终失败优雅返回 `Step stopped: model error`，不抛异常杀线程 |

**明确不做**：A4 缓存作用域失效、A5 危险 shell denylist、B3 子进程可取消、B4 micro-replan 封顶、B5 未通过外溢、B6/B7 —— 属 P1/P2，本次不动。不新增 env 配置项（B1 阈值用构造参数默认值，避免空接配置）。

**依赖前置**：无新依赖。

## §2 目标逻辑链（SSOT）

```
触发入口 → 输入校验 → 核心逻辑 → 持久化/副作用 → 返回/展示 → 失败与回滚
```

### A1 edit_file
- **入口**：executor 调 `edit_file(path, old_string, new_string, replace_all?)` → `registry._edit`。
- **校验**：path 经 `FileOps._resolve` 工作区禁越界；deliverable 写拦截复用 `deliverable_write_blocked`；old==new 报错；old 在文件中出现 0 次→报错、>1 次且非 replace_all→报错（要求加上下文）。
- **核心**：`FileOps.edit_file` 读文件→替换→写回。
- **副作用**：写前 `turn_journal.record_file_before_write`（支持 /undo）；写后 `memory.record_file/record_fact` + `record_structured_key` + `_invalidate_cache`，与 `_write` 对齐。
- **返回**：`OK: edited <path> (<n> replacement(s))`。
- **失败回滚**：匹配失败时不写盘、原文件不变，返回 ERROR。
- **验收**：唯一匹配替换成功；歧义/未命中报错且不写盘；replace_all 多处替换；写后缓存失效、memory 有记录。

### A2 read_file offset/limit
- **入口**：`read_file(path, offset?, limit?)` → `registry._read`。
- **校验**：offset≥1（1 基），limit>0；越界 offset 返回空提示。
- **核心**：`FileOps.read_file` 按行切片 `[offset-1 : offset-1+limit]`；未传则全量（仍受 max_chars 上限）。
- **副作用**：缓存 key 改为 `read_file:{path}:{offset}:{limit}`，避免不同窗口串味。
- **返回**：内容；max_chars 截断时提示「用 offset=N 续读」。
- **验收**：offset/limit 取到正确行窗；缓存按窗口区分。

### A3 run_shell 保尾
- **入口**：`ShellRunner.run` 输出超 max_chars。
- **核心**：保留 head 段 + tail 段，中间插 `…[truncated N chars]…`；exit 行仍在最前。
- **验收**：长输出结尾的 `=== N passed ===` 等汇总仍可见。

### B1 重复 ERROR 断路
- **入口**：`ExecutorAgent.execute` 工具结果处理。
- **核心**：新增 `err_counts`；当结果以 `ERROR` 开头，按签名累加；`err_counts[sig] >= error_repeat_threshold(默认2)` → `_commit_evidence` 返回 `MICRO_REPLAN_NEEDED:{sig}`。
- **边界**：`Step stopped`/`[cached]` 不计入；权限拒绝类 ERROR 也算重复（重复撞墙应换路）。
- **验收**：连续 2 次相同 ERROR run_shell → 返回 MICRO_REPLAN_NEEDED（不等 20 轮）。

### B2 invoke 兜底
- **入口**：`ExecutorAgent.execute` 的 `self._llm.invoke(messages)`。
- **核心**：try/except 包裹，最多重试 `_INVOKE_RETRIES` 次（短 sleep）；仍失败 → `_commit_evidence` 返回 `Step stopped: model error: <exc>`。
- **失败回滚**：不抛异常，交由 graph 正常按 step_output 走 exec_review，不杀后台线程。
- **验收**：invoke 持续抛异常时 execute 返回 `Step stopped: model error`，不抛出。

## §3 实施记录

- **A1**：`FileOps.edit_file`（唯一匹配/replace_all/未命中/歧义校验）+ `registry._edit`（走 deliverable 拦截、journal 快照、memory 记录、缓存失效）+ `EditArgs` schema + `_build` 注册 `edit_file`（WRITE 权限）。executor SYSTEM 提示优先用 edit_file。
- **A2**：`FileOps.read_file(offset, limit)` 行级窗口 + 续读提示；`registry._read` 缓存 key 加入 `:{offset}:{limit}`；`ReadArgs` 加 offset/limit。
- **A3**：`ShellRunner.run` 超限改 head(40%)+tail(60%)，中间插 `[truncated N chars in the middle]`，exit 行仍在最前。
- **B1**：`ExecutorAgent` 新增 `error_repeat_threshold=2` + `err_counts`；结果以 `ERROR` 开头按签名累加，达阈值即返回 `MICRO_REPLAN_NEEDED`。
- **B2**：新增 `_InvokeFailed` + `_invoke_llm`（重试 `_INVOKE_RETRIES=2`，间隔 `_INVOKE_BACKOFF=1.5s`）；execute 内捕获 `_InvokeFailed` 返回 `Step stopped: model error: ...`，不抛异常。
- **偏离说明**：测试 `_BudgetLLM` 原以「数 ToolMessage」驱动状态机，在历史摘要后会误判而重读同一文件（被 B1 正确拦截）。改为以自身 `self.calls` 计数驱动，保留「不同失败探测不烧预算」的原意且对摘要鲁棒。
- **清理**：删除临时调试脚本 `_dbg.py`；无未用 import/死代码。

## §4 自查结论（阶段二回填）

| 环 | 结论 | 指向 |
|----|------|------|
| 触发入口 | ✓ edit_file/read_file(offset) 经 registry 注册可被 executor 调用；executor 调 `_invoke_llm` | `registry.py` `_build`/`_edit`/`_read`，`executor.py` `_invoke_llm` |
| 输入校验 | ✓ 越界 path、deliverable 拦截、old==new/空/未命中/歧义、offset 越界 | `file_tools.edit_file/read_file`，`registry._edit/_read` |
| 核心逻辑 | ✓ 精确替换 / 行窗 / head+tail / err_counts 阈值 / invoke 重试 | 见 §3 |
| 持久化副作用 | ✓ edit 走 journal 快照 + memory 记录 + 缓存失效，与 write 对齐 | `registry._edit` |
| 返回/展示 | ✓ OK/ERROR 文案明确；截断给续读提示；保尾让审查看到汇总 | `file_tools`/`shell_tools` |
| 失败回滚 | ✓ 匹配失败不写盘；invoke 失败优雅停步不杀线程；重复 ERROR 转 micro-replan | `file_tools.edit_file`，`executor` B1/B2 |

**用户负担自查**：pytest / selfcheck / lint 均由 agent 执行；无新增 env 配置（B1 阈值用构造默认值）；无需用户操作。

**验证**：`pytest tests/`（忽略 e2e_live）**174 passed**（+6）；`python -m bobanana --selfcheck` tools/graph PASS；lint clean。新增测试：`test_read_file_offset_limit_window`、`test_edit_file_unique_ambiguous_and_missing`、`test_edit_file_via_toolbox_invalidates_cache`、`test_shell_truncation_keeps_tail`、`test_executor_repeated_error_triggers_micro_replan_fast`、`test_executor_invoke_failure_degrades_gracefully`。
