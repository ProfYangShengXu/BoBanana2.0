# 自主运营运维模块（Autonomous Ops）

Agent 在代码交付前按本清单**自行执行**运维与验证。默认全部由 agent 完成；仅「需用户」项可向用户索取。

---

## 交付前自检清单（通用）

复制并逐项执行，未适用则标 `N/A` 并说明原因：

```
运维自检：
- [ ] 依赖：安装/锁定（npm/pnpm/yarn/pip/go mod 等）— Agent
- [ ] 静态检查：lint / typecheck — Agent
- [ ] 构建：production 或等价 build — Agent
- [ ] 测试：单元/集成（存在则必跑）— Agent
- [ ] 启动验证：dev server 或一次性 smoke（能起则起）— Agent
- [ ] 健康检查：HTTP/curl、端口监听、进程状态 — Agent
- [ ] 日志：启动或请求后无致命 ERROR — Agent
- [ ] 配置：.env.example / 配置项文档已更新 — Agent
- [ ] 迁移：DB migrate / seed（有则跑）— Agent
- [ ] 密钥与生产写操作 — 需用户
```

---

## 按项目类型的命令参考

执行前先看项目根目录标识文件，选用对应一组；**不要猜测**，找不到脚本就读 `package.json` / `Makefile` / `pyproject.toml` / `Cargo.toml`。

### Node / TypeScript

```bash
npm ci || npm install
npm run lint --if-present
npm run typecheck --if-present
npm test --if-present
npm run build --if-present
```

### Python

```bash
pip install -e ".[dev]" 2>/dev/null || pip install -r requirements.txt
ruff check . 2>/dev/null || flake8 .
pytest -q 2>/dev/null || python -m pytest -q
```

### Go

```bash
go mod download
go vet ./...
go test ./...
go build ./...
```

### Rust

```bash
cargo fmt --check
cargo clippy -- -D warnings
cargo test
cargo build
```

### Docker -compose 服务

```bash
docker compose config
docker compose up -d --build
docker compose ps
docker compose logs --tail=50
# 若有 healthcheck URL：
curl -sf http://localhost:<port>/health || curl -sf http://localhost:<port>/
```

---

## 服务与健康检查

| 目标 | Agent 动作 |
|------|------------|
| API 是否存活 | `curl -sf` 或项目内 e2e 脚本 |
| 端口占用 | `netstat` / `ss` / `lsof`（按 OS） |
| 进程是否退出 | 查看 terminal 输出或 `docker compose ps` |
| 错误日志 | 读最近 50–100 行，区分「预期警告」与「交付阻塞错误」 |

失败时：**先自行排查修复**（配置、端口、依赖、迁移），再汇报；不要把「帮你看一下日志」作为第一选项抛给用户。

---

## Agent 必做 vs 仅可请求用户

| 类别 | 执行方 |
|------|--------|
| install / build / test / lint / migrate（非生产） | Agent |
| 读仓库内日志、终端输出、CI 配置 | Agent |
| 更新 `.env.example`、README 运行段 | Agent |
| 本地起停 dev 服务、smoke 请求 | Agent |
| 生产 deploy、删库、改账单、创建云资源 | 需用户明确授权 |
| 填入真实 API Key / 密码 | 需用户提供或配置 |

---

## 交付阻塞 vs 可接受警告

**阻塞（必须修复后才能说完成）**：

- 构建失败、测试失败、lint 对本次改动文件报错
- 服务启动即崩溃、核心 API 5xx
- 迁移失败、数据不一致风险

**可记录但不阻塞（须在交付摘要中说明）**：

- 全仓库历史 lint 与本次无关
- 缺少 E2E 环境但单元测试已通过
- 需用户密钥才能完成的集成（已给出最小步骤）

---

## 扩展本项目运维约定

若仓库存在以下路径，**优先遵循仓库约定**（覆盖本文件通用项）：

- `docs/ops/RUNBOOK.md`
- `scripts/verify.sh` / `scripts/smoke.sh`
- `.github/workflows/*.yml`（本地可复现的 check 命令）
- `Makefile` 的 `verify` / `ci` target

发现上述文件时，在交付摘要的「自主验证」一节注明：**遵循项目 RUNBOOK：\<路径\>**。
