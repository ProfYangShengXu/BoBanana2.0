# 更新日志：便携安装跨平台 + API 配置向导

**版本目标**：2.1.5 (`portable-install`)

## 1. 目标

- 安装包在 Windows / macOS / Linux 均可一键安装
- API Key / Base URL / Model 可交互配置（安装时 + `bb config` + `--configure`）
- `INSTALL.md` 幼儿园级分步教程（中文）

## 2. 逻辑链

```
用户 → install.cmd|install.sh|python install.py
  → 检测 OS + Python 3.10+
  → 创建 .venv + pip install
  → env_setup.configure_api (交互/CLI)
  → bobanana --selfcheck
  → Windows: 桌面快捷方式 / Unix: 打印 bb.sh 用法

运行时 → bb config / python -m bobanana --configure
  → env_setup 读写 .env（不泄露完整 key）
```

## 3. 改动清单

| 文件 | 改动 |
|------|------|
| `bobanana/env_setup.py` | 新建：.env 读写、提供商预设、交互向导 |
| `install.py` | 新建：跨平台安装主入口 |
| `install.sh` / `bb.sh` | 新建：Unix 启动包装 |
| `install.ps1` / `bb.ps1` | 调用 env_setup；新增 `config` |
| `bobanana/__main__.py` | `--configure` |
| `pack.ps1` | 打包校验新入口 |
| `INSTALL.md` | 幼儿园级中文教程 |
| `tests/test_env_setup.py` | 单元测试 |

## 4. 阶段二自查结论（交付前填写）

- [x] 入口/数据流/分支与计划一致（install.py/sh/cmd → venv → env_setup → selfcheck）
- [x] 验收满足：`102 passed` pytest；`--selfcheck` PASS；`pack.ps1` 生成 zip；`install.py --skip-api-key` 可跑通

**偏差说明**：无。`install.py` 优先使用 `sys.executable`，避免在已有 `.venv` 内找不到系统 `python`。
