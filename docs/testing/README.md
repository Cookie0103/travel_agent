# 测试总览

怎么测、测什么、环境要求、CI 做什么、已知的环境相关失败。**验收矩阵（需求→验证→缺口）不在这里复制**，见 [execution/verification.md](../execution/verification.md)。命令全部经 `uv run python scripts/dev.py <子命令>`（项目唯一开发入口）。数据核对日期：2026-10-18，来源 `pyproject.toml`、`scripts/dev.py`、`.github/workflows/check.yml`。

## 1. 测试分层与命令

| 层 | 位置 | 命令 | 需要 | 说明 |
| --- | --- | --- | --- | --- |
| 静态检查 | 全仓 | `dev check` | uv 环境 | ruff、ruff format、mypy `--strict`（win32/linux/darwin 三平台）、`lint-imports`（分层契约）、`scripts/check_docs.py`（文档入口） |
| 单元/离线 | `tests/test_*.py` | `dev test`（`--path tests/xxx.py`、`--keyword 名称` 专项） | 无 | 默认 `-m 'not live'`；不调用真实模型/供应商；约束见 [tests/README](../../tests/README.md) |
| 真实 PG 集成 | `tests/integration/`（`@pytest.mark.integration`） | `dev db-up` 后 `dev test`（也含此层）；仅此层：`uv run pytest -m integration` | Docker + PostgreSQL | 随机临时库、执行两遍 Alembic 迁移与 schema drift 检查，只清理本次建的库；PG 不可用时**失败**而非跳过。见 [integration/README](../../tests/integration/README.md) |
| 真实外部 live | `tests/live/`（`@pytest.mark.live`） | `TRAVEL_REAL_API_PROBE=geocode\|places\|routes\|rakuten\|weather` 后 `python -m pytest -m live tests/live/test_real_apis.py -q` | 授权 + key + 预算 | 默认不跑、不进 CI；一次一个接口。见 [live/README](../../tests/live/README.md) |
| 前端 | `apps/web/tests/*.test.ts` | `dev web-check`（类型 → lint/prettier → `node --test` → build）；Turbopack 受限时加 `--webpack` | Node 24+、pnpm 11 | 只覆盖 `lib` 纯函数，**不证明页面可渲染**；契约变化先 `dev web-generate`。见 [apps/web/README](../../apps/web/README.md) |
| 浏览器验收 | 真实 Chrome | `dev db-up`、`dev api`、`dev web` 后手动走流程 | 同上 | 要求与失败恢复路径见 [FRONTEND.md](../guides/FRONTEND.md)；截图证据放 [evidence/](../evidence/README.md) |
| 评测 | `eval/` | `dev eval-dev`（旧）；`eval-v2`、`eval-memory`、`eval-simulator` 及 `--live` 变体 | PG；live 另需授权 | 离线默认用 MockTransport 与随机库；口径见 [guides/evaluation.md](../guides/evaluation.md)，V2 操作见 [operations/interaction-memory-eval.md](../operations/interaction-memory-eval.md)，入口 [eval/README](../../eval/README.md) |
| 故障注入 | `mock_supplier/` | `dev supplier`（端口 8001）；测试在 `tests/integration/test_supplier.py` | PG | `X-Mock-Fault`：delay / rate_limit / server_error / lose_response，仅 `--faults` 显式启用。见 [mock_supplier/README](../../mock_supplier/README.md) |
| 容器演示 | `scripts/smoke_demo` | `dev stack-up` → `python -m scripts.smoke_demo` → `dev stack-down` | Docker | 离线容器端到端，含停启后读取 |

## 2. 前置条件

- **一键自检**：`uv run python scripts/dev.py doctor` 只读检查 Python 3.12、uv、Node 24+、pnpm 11、claude CLI 是否在白名单、PG（TCP 5434）、pytest 临时目录是否可写，失败项给修复提示，有失败退出码 1（2026-10-18 新增）。
- **Python**：uv，`dev setup` 安装依赖与 pre-commit 钩子；uv 缓存在项目 `.cache/`。
- **PostgreSQL**：`dev db-up` 用 `docker compose` 启动 `postgres:17`，仅监听 `127.0.0.1`，**宿主端口默认 5434**（`POSTGRES_PORT`），`.env` 必须提供 `POSTGRES_PASSWORD`。Docker 不可用时 `db-up` 返回非零并写入 [blocked/environment.md](../blocked/environment.md)（该文件由脚本写，勿移动）。
- **Node/pnpm**：Node 24+、pnpm 11（CI 固定 11.19.0）；`dev web-setup` 安装。
- **Claude CLI**：SDK 路线测试需要本机 `claude`，可用 `TRAVEL_CLAUDE_CLI` 指定。关闭自动压缩的路径只接受白名单版本，见 `backend/providers/claude_agent/runtime.py`：SDK 0.2.163 配 CLI **2.1.114 / 2.1.294 / 2.1.295**，其他版本返回 `blocked: auto_compaction_capability`。CI 固定安装 2.1.295。
- **live 测试**：显式 `--live`/环境变量、`.env` 密钥、每日预算（DeepSeek ≤15 CNY 等，见各批次授权）；不因有 key 自动放开。

## 3. CI（`.github/workflows/check.yml`，push 与 PR 触发）

| 作业 | 做什么 |
| --- | --- |
| `python` | ubuntu + `postgres:17` 服务；Node 24 + `claude-code@2.1.295`；`uv sync --locked`；`dev check`；`dev test`（含真实 PG 集成） |
| `web` | pnpm 11.19.0；`pnpm install --frozen-lockfile`；typecheck、lint、test、build |
| `docker-demo` | `stack-up` → `smoke_demo` → `stack-down` → 再 `stack-up` → `smoke_demo --verify`（验证重启后读取）→ `stack-down` |

CI 不配置任何模型凭据，不跑 live 与评测。

## 4. 已知环境相关失败

这些不是业务缺陷，遇到先对照此表，不要改断言或跳过测试。

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| Windows 上直接用 `asyncio.run` / `asyncio.Runner()` 的测试或脚本连接 PG 报错（曾导致 4 例集成测试失败） | Windows 默认 Proactor 事件循环与 psycopg 不兼容 | **2026-10-18 已修复**：用 `asyncio.Runner(loop_factory=asyncio.SelectorEventLoop)`；`tests/test_event_loop_entrypoints.py` 用 AST 扫描 `scripts/` 与 `tests/integration/`，新增裸 `asyncio.run` 会报红（[P-F1](../plans/2026-10-18-completeness-hardening.md)）。Linux/CI 不受影响 |
| `tests/test_evaluation_variants.py` 中 4 例返回 `blocked` | 本机 CLI 为 2.1.302（或其它不在白名单的版本），触发 `auto_compaction_capability` | 先跑 `uv run python scripts/dev.py doctor` 看本机 CLI 是否在已验证列表；在进程内设置 `TRAVEL_CLAUDE_CLI` 指向 2.1.295 的 CLI，或 `npm install --global @anthropic-ai/claude-code@2.1.295`；不改 `.env` 或 `runtime.py` 白名单（新增版本须先独立离线核验；是否加入白名单见批次计划待决 D5） |
| `tests/test_travel_sdk_offline.py::...[anthropic-claude-haiku-5-5]` 失败（`provider_error / invalid_assistant_message`） | **既有问题**：在未修改的 HEAD（`13e3c20`）上同样失败（2026-10-18 用干净 worktree 验证），与 2026-10-18 批次无关；原因未查清，另外两个变体（deepseek、haiku-4-5）通过 | 暂不处理；查清前不要为它改断言 |
| 直接 `pytest` 报临时目录 `PermissionError`，或集成测试出现大量 ERROR | 复用了他人/沙箱遗留的 pytest 临时目录 | **2026-10-18 已修复**：`tests/conftest.py` 在未设置 `PYTEST_DEBUG_TEMPROOT` 时把临时根指向 `.cache/pytest-tmp`；`dev test` 仍每次建新目录（`.cache/pytest-runs/`） |
| `web-check` 的 Turbopack CSS 子进程 `Operation not permitted`；`dev web` 开发服务器首页 500（`Cannot find module '@tailwindcss/postcss'`，浏览器验收时复现） | 本机端口/权限限制，Turbopack 的 CSS 子进程起不来 | `dev web-check --webpack`、`dev web --webpack`（2026-10-18 新增；检查项不减少），详见 [operations/interaction-memory-eval.md](../operations/interaction-memory-eval.md) |
| 本地前端指定别的 API 端口时启动即报 `TRAVEL_API_ORIGIN must be a local, Compose or Railway private API` | `apps/web/next.config.ts` 的白名单只放行 `http://127.0.0.1:8000`、`http://api:8000` 与 railway.internal，是有意的 SSRF 防护；`backend/server.py`、`mock_supplier/server.py` 端口也写死 | 并行起多套环境时先停占用 8000 的进程；不要放宽白名单 |
| 7 例本机失败（ANTHROPIC_BASE_URL 指向公司网关 3 个；CLI 2.1.299 不在白名单 4 个） | 2026-10-15 记录于[提速批次进度](../plans/2026-10-15-speed-repair-and-form.md)；与上两行同类 | 同上 |
| 全量测试耗时接近外层 600 秒上限 | 整套 PG/SDK 回归约五分钟 | 先专项 `--path`，完整 `dev test` 在保存关卡跑一次 |

## 5. 记录测试怎么写（沿用 [plans/README](../plans/README.md)）

- 测试计划、先红后绿输出、测过哪些方案最后选哪个：写在批次计划的 **任务表验收条件** 与 **§8 P-条目**（索引：[问题与修复索引](../plans/problems.md)），取舍上升为 [ADR](../adr/README.md)。
- “离线通过 / PG 集成 / 浏览器 / 真实 API / 独立审查”分别写，不合并；结论标 VERIFIED / REASONED / ASSUMED。
- 评测对照的结论（冻结 40×3、同源码受控对照等）见 [QUALITY_SCORE](../guides/QUALITY_SCORE.md) 与 [evidence/](../evidence/README.md) 的 `m42-*`。
- 新增环境相关失败：先在上表加一行（现象、原因、处理），再在批次计划记录。
