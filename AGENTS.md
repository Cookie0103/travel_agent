# AGENTS.md — 给 AI 编码助手的执行规则

本文件是 AI（Codex 等）在本仓库工作的入口。人读的设计文档在 `plan/`，**设计以 `plan/` 为唯一来源**；本文件只规定「怎么执行」。两者冲突时，停下来问用户，不要自行选择。

## 1. 开工前读什么

1. `plan/README.md`：文档地图与项目边界。
2. `plan/实操计划/04-开发任务计划.md`：找到当前任务 ID 和依赖。
3. `docs/tasks/<里程碑>.md`：当前任务的可执行规格（输入、产出、验收命令）。
4. 只读当前任务涉及的部分：`02`（架构）、`03`（领域与工具）、`05`（验收），以及 `docs/adr/`。
5. 上游参考代码在 `vendor/`（获取方式见 `docs/tasks/M0.md` 的 M0.1）。只读，不修改，不复制进本仓库，除非 ADR 明确允许。

不要一次读完全部文档，也不要实现当前任务以外的东西。

## 2. 工作流程：批次模式（无人值守运行）

用户不在线时运行一批任务，白天逐个 commit 审阅学习。原则：**不停下来等人，但每个决定都留下可审阅的记录；错误不能跨过审阅关卡叠加。**

### 2.1 一批任务怎么跑

1. 从最新的 `main` 建分支：`batch/<日期>-<主题>`，例如 `batch/2026-10-03-m0-core`。
2. 按用户在启动提示中给出的任务列表，按 04 的依赖顺序执行。同一批内，后面的任务可以基于前面任务的代码。
3. **关卡任务**（§2.3）做完后，本批不再开始任何依赖它的任务；改做列表中不依赖它的任务，没有就结束本批。
4. 每个任务完成 = `dev check` 和 `dev test` 都通过（命令见 §4） + 一个 commit。commit message 用 `<任务ID>: <一句话>`。
5. 同一个任务连续两次验证失败：把未完成的改动放进 `wip/<任务ID>` 分支，在 `BLOCKED.md` 记录，跳过它和所有依赖它的任务，继续做其他任务。
6. 全部做完或无任务可做时，写 `docs/review/<分支名>.md` 的批次总结（§2.4），然后结束。**不合并到 `main`，不 push。**

### 2.2 遇到不明确的地方

不停工、不问人。按以下顺序处理：
1. `plan/` 和 `docs/` 里有答案的，照做；
2. 没有答案的，选最保守、最容易回退的做法；
3. 在 `docs/decisions-pending.md` 追加一条：任务 ID、问题、选了什么、备选是什么、为什么、如果用户不同意要改哪些文件。

**不能自行决定的事**（遇到就记入 `BLOCKED.md` 并跳过）：修改 `plan/` 的设计、新增 ADR 以外的依赖、修改已合并到 `main` 的公共接口、角色人设内容（M0.7）。

### 2.3 关卡任务（审阅通过并合并后，依赖它的任务才能开始）

这些任务决定了后面大量代码的形状，设计错了会导致后续全部返工：

| 关卡 | 原因 |
| --- | --- |
| M0.2 DeepSeek 协议实测 | 结论决定消息格式和循环的处理方式 |
| M0.3 中立消息格式 | 全部模型调用都建立在它上面 |
| M1.3 TravelRequest / Evidence | 状态与事实时效的基础 |
| M1.6 validator + 反思循环 | 核心 Agent 机制 |
| M1.7 PlanPatch 与确认保存 | 条件更新与幂等的第一次实现 |
| M2.2 Booking 状态机 | 预订安全的核心 |
| M2.4 断点与恢复 | 恢复语义影响所有写操作 |

非关卡任务可以在同一批内连续执行。

### 2.4 每个任务留下的审阅材料

每个任务在 `docs/review/<任务ID>.md` 写（中文，不超过 60 行）：
- **阅读顺序**：先看哪个文件哪个函数，再看哪个；
- **主调用链**：从入口到结果经过哪些模块，状态在哪里读写；
- **不变量**：必须保持的规则，以及由哪个测试保护；
- **失败处理**：哪些情况会失败，怎么处理；
- **取舍**：选了什么方案、一个备选方案、为什么不选它；
- **验证**：运行的命令和输出摘要（真实输出，不能编造）；
- **理解问题**：3–4 个，只给问题。用户白天在同一文件下方写回答。

批次总结 `docs/review/<分支名>.md`：完成的任务和 commit 列表、跳过的任务及原因、`decisions-pending.md` 新增条目、建议的 commit 阅读顺序。

### 2.5 白天审阅后（由用户触发，不在批次内做）

用户读完并回答理解问题后，会让 AI：根据回答修正代码或文档、更新 `04` 的任务状态和证据、在 `docs/journal.md` 追加记录（模板见 `plan/项目掌握与AI协作.html` 第 06 节）。合并到 `main` 由用户执行。

### 2.6 新里程碑

一个里程碑开始前，如果 `docs/tasks/<里程碑>.md` 不存在，单独开一批只写这份规格（按 `docs/tasks/M0.md` 的格式），不写代码。用户确认后再开始执行该里程碑。

### 2.7 并行

不依赖任何未合并代码的任务，可以从 `main` 另开分支并行执行（例如用户白天审阅时）。并行分支之间不能互相依赖。

## 3. 代码规范（企业级 + 用户能读懂）

### 3.1 硬性约束（CI 检查，不通过不算完成）
- 类型：`mypy --strict` 通过；禁止 `Any` 出现在公共接口；不加 `# type: ignore`，除非附理由注释。
- Lint / 格式：`ruff check` 与 `ruff format --check` 通过。
- 分层依赖（用 import-linter 检查）：
  - `domain/` 不 import 本项目的任何其他层，也不 import 外部 SDK；
  - 外部 SDK（anthropic、openai、mcp、httpx 调外部服务）只能出现在 `providers/`、`adapters/`、`mcp/`；
  - `api/` 只调用 `services/` 和 `agent/`，不直接访问 `persistence/`。
- 新增依赖必须先写 ADR（`docs/adr/`），说明为什么不用标准库或已有依赖。
- 不吞异常：禁止裸 `except:` 和 `except Exception: pass`；错误按 02 §8.3 的错误码分类返回。
- 金额用 `Decimal`；时间带时区；ID 由服务端生成。
- 不修改生成的文件（迁移以外的自动生成物、lock 文件除外由工具更新）。

### 3.2 可读性约束（让用户能读懂）
- 每个模块文件开头写 docstring：这个模块解决什么问题、在主调用链的哪个位置。
- 每个包有一个 `README.md`（不超过 30 行）：职责、入口函数、关键流程、必须保持的不变量。
- 注释写「为什么」，不写「做了什么」。关键不变量用 `# 不变量：` 开头注明。
- 函数不超过约 50 行，嵌套不超过 3 层；超过就拆。
- 命名用领域词（见 02 §0 的 6 个概念），不发明新术语。
- 测试名描述行为，例如 `test_duplicate_confirm_returns_same_booking`。

### 3.3 测试要求
- 每个新行为至少有一个**失败路径**测试（错误输入、缺数据、下游出错）。
- 测试默认不调用真实模型，用 FakeClient（参考 `vendor/commerce-agents/commerce-common/commerce_common/testing.py` 的思路）。
- 涉及事务和恢复的测试必须用真实 PostgreSQL（docker），不能 mock 持久化层。
- 对应 05 回归矩阵的测试，在测试 docstring 里写上 R 编号。

## 4. 命令（M0.1 完成后生效）

统一入口 `scripts/dev.py`（纯 Python，Windows / macOS / Linux 通用），下文简写为 `dev`：

```text
uv run python scripts/dev.py setup      # uv sync + 安装 pre-commit
uv run python scripts/dev.py check      # ruff check + ruff format --check + mypy --strict + lint-imports
uv run python scripts/dev.py test       # pytest（不含 live 测试）
uv run python scripts/dev.py db-up      # docker compose 启动 PostgreSQL
uv run python scripts/dev.py eval-dev   # 评测 dev 集（默认 FakeClient）
```

真实模型调用只允许在显式标记下运行：`pytest -m live` 或 `dev eval-dev --live`。

### 4.1 运行环境：Windows 兼容（硬性要求）

项目在 **Windows** 上由 Codex 执行，所有代码、脚本、命令必须在 Windows 原生（PowerShell）下可用，同时不破坏 macOS / Linux。

- **不用** Makefile、`.sh` 脚本、bash 语法（`&&` 之外的管道技巧、`export`、`$(...)`）。任务脚本一律用 Python 写。
- 路径用 `pathlib.Path`，不拼接 `/` 或 `\\` 字符串；不硬编码盘符和绝对路径。
- **文件读写必须显式 `encoding="utf-8"`**（Windows 默认是 cp936 / cp932，会把中文、日文读写成乱码）。`scripts/dev.py` 启动时设置 `PYTHONUTF8=1`，子进程继承。
- 换行统一 LF（`.gitattributes` 已约束）；不提交 CRLF。
- 环境变量在 `scripts/dev.py` 内设置，不要求用户在 shell 里 `export`。
- 不依赖符号链接、`chmod`、`/tmp`。临时文件用 `tempfile`。
- Docker 使用 Docker Desktop（WSL2 后端）。涉及 `docker compose` 的任务，启动前先检查 Docker 是否在运行，没运行就在 `BLOCKED.md` 记录并跳过，不要卡住。
- 拉取 DataMind 需要用户的 GitHub 凭据；拉取失败不是致命错误（见 M0.1）。

## 5. 密钥、费用与安全

- 密钥只从环境变量读取（`.env` 本地文件，已在 `.gitignore`）；提交 `.env.example`，只写变量名不写值。
- 绝不把密钥写进代码、测试、日志、trace 或文档。
- 真实模型调用必须经过预算检查：`DAILY_BUDGET_USD`（默认 1）超出即停止。
- `vendor/` 已在 `.gitignore`。其中 DataMind 是组织内部仓库，**任何内容都不能提交到本仓库**（本仓库是公开的）；评测用例改编后的版本可以提交，原文件不行。
- 日志在 INFO 级别不输出完整 prompt 和工具结果。

## 6. 不要做的事

- 不实现 04 中 C 档的内容（只写 ADR）。
- 不引入 Agent 框架（LangChain / LangGraph 等）、Redis、消息队列、向量库。
- 不 push、不合并到 `main`、不改已有 commit 的历史、不删除分支。
- 不跳过 `dev check` / `dev test` 提交；不用 `--no-verify`。

## 7. 启动提示模板（用户复制给 Codex）

```text
读 AGENTS.md，按 §2 批次模式工作。
分支：batch/<日期>-<主题>
任务：<任务ID 列表，例如 M0.1 M0.2 M0.3 M0.4>
真实模型调用：<允许 / 不允许>；DAILY_BUDGET_USD=<金额>
做完或无任务可做时，写批次总结后结束。
```
- 不为了让测试通过而修改测试的断言，除非说明该断言本身错在哪里。
