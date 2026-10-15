# ADR-001 开发入口与提交检查

状态：accepted（2026-10-02，M0.1 执行规格要求）

## 决策
- 新增仅开发依赖 `pre-commit`，执行 M0.1 已规定的提交钩子安装。
- 使用本地 hooks，调用同一套 `dev check` / `dev test`，不再下载另一套 lint 工具。
- 标准库能启动子进程，但不提供成熟的 Git hook 安装与暂存区处理；不自建替代品。
- M0.1 只安装测试与检查工具；各业务依赖在对应任务首次使用时按 ADR-000 引入，避免空骨架提前固定未使用 SDK 的接口。
- Python 要求 3.12；`uv.lock` 由 uv 生成。`uv` 缓存放项目内 `.cache/uv`，避免本机默认缓存权限问题。
- 预提交缓存使用项目内 `.cache/pre-commit`（dev 入口设置）；不提交缓存或环境。
- 2026-10-03 修复：Ruff 只处理 Python 文件及 pyproject；dev test 每次用 tempfile 在项目内创建独立临时目录，并将 pytest 缓存放同一目录，避免终端与沙箱的权限交叉。保留旧现场，不修改系统 ACL。

## 备选与回退
- 备选：手写 `.git/hooks/pre-commit`。不选：难以跨平台安装和维护，且背离 M0.1 规格。
- 若改用其他提交工具，修改 pyproject.toml、uv.lock、.pre-commit-config.yaml 和 scripts/dev.py。
