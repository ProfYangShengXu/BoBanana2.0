# P1 工具链 + 执行层加固

> 背景：承接 P0（见 `2026-05-31-p0-toolchain-exec-hardening.md`）。本次落地 P1：B3 子进程可取消、A4 缓存按路径作用域失效 + key 规范化、B4 micro-replan 每步封顶。
> 注：原批判中的 B5（未通过步骤外溢到最终结论）经核查 graph 已实现（`failed_steps` + `[未通过审查/UNVERIFIED]` + `status=partial` + finalize 列出），本次不重复做。

## §1 计划更新

| # | 改动 | 文件 | 说明 |
|---|------|------|------|
| B3 | run_shell 子进程可取消 | `tools/shell_tools.py`、`tools/registry.py`、`graph.py` | ShellRunner 持 `cancel_event`；设置后改用 Popen 轮询，取消即 `kill` 并返回；graph.set_cancel_event 同时传播到 toolbox.shell |
| A4 | 缓存按路径作用域失效 + key 规范化 | `tools/registry.py`、`memory/manager.py`、`memory/structured_memory.py` | 文件写入只失效相关条目（该文件 read、其父目录 list、引用该路径的 shell）；read/list/shell 缓存 key 规范化（统一分隔符、去 `./`、折叠空白） |
| B4 | micro-replan 每步封顶 | `graph.py`、`config.py`、`.env.example` | 同一步 micro-replan 超过 `max_micro_replans`(默认2) 不再 patch，转为诚实 `Step stopped` 交 exec_review（复用 B5 failed_steps 通道） |

**明确不做**：B5（已实现）；A5 危险 shell denylist、A6 权限确认、B6 摘要阈值、B7 sentinel 常量化（P2）。run_shell 写类操作仍全清缓存（路径未知，保守）。

**依赖前置**：无新依赖。新增 1 个 env：`BOBANANA_MAX_MICRO_REPLANS`。

## §2 目标逻辑链（SSOT）

```
触发入口 → 输入校验 → 核心逻辑 → 持久化/副作用 → 返回/展示 → 失败与回滚
```

### B3 子进程可取消
- **入口**：submit_task → `graph.set_cancel_event(rt.cancel_event)`（已有）→ 新增传播到 `toolbox.shell.cancel_event`；executor 调 run_shell → `ShellRunner.run`。
- **校验**：cancel_event 为 None 时走原阻塞 `subprocess.run`（保持既有行为/测试）。
- **核心**：cancel_event 非 None → `Popen` + `communicate(timeout=0.25)` 轮询；取消置位即 `kill()` 收尾。
- **副作用**：进程被终止。
- **返回**：取消时返回 `ERROR: command cancelled by user (process terminated).`；executor 每次工具调用后的 cancel 检查随即返回 `Step stopped: cancelled by user.`。
- **失败回滚**：超时仍返回原 TIMEOUT 文案触发 replan；输出格式（exit 行 + head+tail 截断 + posix 提示）不变。
- **验收**：cancel_event 预置时 run 立即 kill 返回；长命令可被打断；None 时行为与原一致（现有 shell 测试不破）。

### A4 缓存作用域失效 + key 规范化
- **入口**：`_write`/`_edit` 成功 → `_invalidate_cache(reason, path=P)`；`_read`/`_list`/只读 `_run_shell` 生成 key。
- **校验**：P 规范化（`\\`→`/`、去前导 `./`、去引号空白）。
- **核心**：`structured.clear_exploration_for_path(P)` 删除：read_file args==P、list_dir args∈{P 父目录, 根, P 本身或 P 的祖先目录}、run_shell args 含 P 子串；其余保留。key 规范化：read_file/list_dir 用规范化路径，只读 shell 折叠空白。
- **副作用**：仅相关缓存行删除。
- **返回/展示**：日志 `exploration cache invalidated (scope=<path>): N`。
- **失败回滚**：run_shell 写类（路径未知）仍 `_invalidate_cache(reason)` 全清。
- **验收**：写 a.py 不清 b.py 的 read 缓存；清掉 a.py 的 read 与其父目录 list；不同写法的同一路径命中同一 key。

### B4 micro-replan 每步封顶
- **入口**：execute 返回 `MICRO_REPLAN_NEEDED` → route micro_replan → `_micro_replan_node`。
- **校验**：读 `scratch["_micro_replans"][idx]`。
- **核心**：自增计数；`> max_micro_replans` → 不再 patch，置 `step_output = "Step stopped: stuck after N local replans on this step."`。
- **副作用**：plan 不变（未 patch）；replan/新计划时清空计数。
- **返回/展示**：新增 `_route_after_micro_replan`：step_output 以 `Step stopped` 开头 → exec_review，否则 execute。
- **失败回滚**：诚实失败经 exec_review → advance 记入 `failed_steps`、status=partial（复用 B5）。
- **验收**：同一步反复 MICRO_REPLAN 在第 N+1 次转 Step stopped 并进 exec_review，不无限 patch。

## §3 实施记录

- **B3**：`ShellRunner` 加 `cancel_event` 参数 + `_run_cancellable`（Popen + `communicate(timeout=0.25)` 轮询）+ `_kill_tree`（Windows `taskkill /F /T /PID`，POSIX `start_new_session` + `os.killpg`）+ `_format_result`/`_timeout_marker` 抽取复用。`Toolbox.set_cancel_event` → `shell.cancel_event`；`graph.set_cancel_event` 传播到 `toolbox.set_cancel_event`。
- **A4**：`structured_memory._norm_cache_path` + `clear_exploration_for_path`（read 精确、list 父/祖先、shell 子串）；`manager.invalidate_exploration(path=None)`；`registry` 中 read/list key 用规范化路径、只读 shell key 折叠空白、`_invalidate_cache(reason, path=None)`，`_write`/`_edit` 传 path，写类 shell 保持全清。
- **B4**：`config.max_micro_replans`(默认2)+env；`_micro_replan_node` 用 `scratch["_micro_replans"][idx]` 计数，超限置 `Step stopped` 不再 patch；新增 `_route_after_micro_replan`；`micro_replan` 边改条件边；`_replan_node` 重置计数。
- **踩坑修复**：B3 首版用 `proc.kill()` 只杀 cmd.exe，孙进程（python）持有 stdout 管道致 `communicate()` 阻塞 20s。改为进程树杀后取消 <1s 生效（测试实测 elapsed<5）。
- **行为变更**：A4 使写无关文件不再失效其它缓存，改写既有测试 `test_exploration_cache_hit_and_invalidation` 以断言作用域语义。
- **清理**：抽取 `_format_result`/`_timeout_marker` 消除重复；无未用 import/死代码。

## §4 自查结论（阶段二回填）

| 环 | 结论 | 指向 |
|----|------|------|
| 触发入口 | ✓ submit_task→set_cancel_event 传播到 shell；write/edit→scoped 失效；execute→MICRO_REPLAN→micro_replan_node | `app.py`/`graph.set_cancel_event`、`registry`、`graph._micro_replan_node` |
| 输入校验 | ✓ cancel_event None 走原阻塞路径；路径规范化；max_micro_replans 读 settings | `shell_tools.run`、`_norm_cache_path`、`graph` |
| 核心逻辑 | ✓ Popen 轮询+树杀 / 作用域删除 / 计数封顶 | 见 §3 |
| 持久化副作用 | ✓ 进程终止；仅相关缓存行删除；plan 在封顶时不变 | `shell_tools._kill_tree`、`structured_memory`、`graph` |
| 返回/展示 | ✓ cancelled 文案；scope 日志；honest Step stopped→exec_review | `shell_tools`、`registry._invalidate_cache`、`_route_after_micro_replan` |
| 失败与回滚 | ✓ 超时仍 TIMEOUT→replan；树杀不阻塞；封顶失败入 failed_steps/partial（复用 B5） | `shell_tools`、`graph` |

**用户负担自查**：pytest/selfcheck/lint 由 agent 执行；`.env.example` 已补 `BOBANANA_MAX_MICRO_REPLANS`；无需用户操作。

**验证**：`pytest tests/`（忽略 e2e_live）**178 passed**（+4 新增，1 既有改写）；`--selfcheck` tools/graph PASS；lint clean。新增/改写测试：`test_shell_cancel_event_terminates_process`、`test_shell_default_path_blocking_unchanged`、`test_cache_scoped_invalidation_and_key_normalization`、`test_micro_replan_cap_stops_after_limit`、`test_exploration_cache_hit_and_invalidation`（改写为作用域语义）。
