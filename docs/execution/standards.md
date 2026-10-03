# 工程、测试、费用与运行标准

从旧 AGENTS.md 移入的强制标准。职责划分以 plan/ 为准；本文件只规定如何实现和验证。2026-10-03：取消人工阶段批准，不降低质量或费用约束。

## 3. 代码规范（企业级 + 用户能读懂）

### 3.1 硬性约束（CI 检查，不通过不算完成）
- 类型：`mypy --strict` 通过；禁止 `Any` 出现在公共接口；不加 `# type: ignore`，除非附理由注释。
- Lint / 格式：`ruff check` 与 `ruff format --check` 通过。
- 分层依赖（用 import-linter 检查）：
  - `domain/` 不 import 本项目的任何其他层，也不 import 外部 SDK；
  - 外部 SDK（claude_agent_sdk、anthropic、openai、mcp、httpx 调外部服务）只能出现在 `providers/`、`adapters/`、`mcp/`；
  - `api/` 只调用 `services/` 和 `agent/`，不直接访问 `persistence/`。
- 新增依赖必须先写 ADR（`docs/adr/`），说明为什么不用标准库或已有依赖。
- 不吞异常：禁止裸 `except:` 和 `except Exception: pass`；错误按 02 §8.3 的错误码分类返回。
- 金额用 `Decimal`；时间带时区；ID 由服务端生成。
- 不修改生成的文件（迁移以外的自动生成物、lock 文件除外由工具更新）。

### 3.2 可读性约束（让用户能读懂）
- 每个模块文件开头写 docstring：这个模块解决什么问题、在主调用链的哪个位置。
- 每个包有一个 `README.md`（不超过 30 行）：职责、入口函数、关键流程、必须保持的不变量。
- 注释写「为什么」，不写「做了什么」。关键不变量用 `# 不变量：` 开头注明。
- 函数以约 50 行、嵌套不超过 3 层为参考；按独立职责拆分，不为凑行数把连续逻辑拆成一串跳转。短代码也必须让调用链清楚。
- 命名用领域词（见 02 §0 的 6 个概念），不发明新术语。
- 测试名描述行为，例如 `test_duplicate_confirm_returns_same_booking`。

### 3.3 测试要求
- 每个新行为至少有一个**失败路径**测试（错误输入、缺数据、下游出错）。
- 测试默认不调用真实模型，用 FakeRuntime / 脚本化 SDK 消息替身（旧探针保留 FakeClient；参考 `vendor/commerce-agents/commerce-common/commerce_common/testing.py` 的思路）。
- 涉及事务和恢复的测试必须用真实 PostgreSQL（docker），不能 mock 持久化层。
- 对应 05 回归矩阵的测试，在测试 docstring 里写上 R 编号。

### 3.4 SDK 优先与简洁复用

2026-10-03 用户明确要求：学习 commerce-agents 的职责划分与复用方式，避免重复封装、过度抽象和难以阅读的碎片代码。这是后续实现与独立审查的要求。

- **先找再写**：先检索仓库已有函数/接口，再核对锁定 SDK 版本的公共 API 与最新官方文档。已有能力可直接用；升级须有需要与兼容验证，不为追新而升级。
- **SDK 管通用运行时**：模型/工具往返、结果回填、会话与上下文能力优先使用 Claude Agent SDK。不另写循环、通用消息协议或工具调度框架；事件转换只保留应用真正使用的字段。
- **业务只写差异**：自写旅行条件、证据时效、行程校验、局部改程、确认/幂等/预订等 SDK 不提供的规则。工具注册/MCP 握手调用 SDK；业务校验保持在本项目。
- **规则只有一个来源**：相同模型/参数/schema、错误分类、费用解析、身份与版本检查复用一个定义。CLI、API、评测共用业务入口；禁止各写一份“略不同”的实现。
- **抽象解决现有问题**：优先小函数和组合；出现真实重复或需要隔离外部系统时再提接口。不要提前造 BaseManager、插件工厂、通用仓储等大框架；不把不同业务规则硬合并成复杂分支。
- **按职责组织文件**：相关逻辑就近放置；不为每个函数单独建文件，不为了显得分层而增加只转发参数的中间层。注释解释约束和取舍，不重复代码。
- **必要保护不扩散**：费用、身份、事务、进程清理集中在边界。自写 SDK 缺失的保护须能指出具体失败证据；不用删除验证、超时或安全检查来缩短代码。
- **参考不盲抄**：commerce-agents 的应用代码不是 SDK 公共 API；借鉴其“配置 → 工具注册 → 执行器 → 结果收集”。不照搬多运行时、演示身份或未经验证的 hook。复制上游代码仍须 ADR 与许可说明。
- **每次独立审查都问**：是否已有函数或 SDK API 可用？同一规则是否重复？每个抽象/文件是否有必要？从入口到业务结果能否顺着读懂？发现问题先简化再继续。

## 4. 命令（M0.1 完成后生效）

统一入口 `scripts/dev.py`（纯 Python，Windows / macOS / Linux 通用），下文简写为 `dev`：

```text
uv run python scripts/dev.py setup      # uv sync + 安装 pre-commit
uv run python scripts/dev.py check      # ruff check + ruff format --check + mypy --strict + lint-imports
uv run python scripts/dev.py test       # pytest（不含 live 测试）
uv run python scripts/dev.py db-up      # docker compose 启动 PostgreSQL
uv run python scripts/dev.py eval-dev   # 评测 dev 集（默认 FakeRuntime）
```

真实模型调用只允许在显式标记下运行：`pytest -m live`、`dev eval-dev --live` 或 M0.4 实现后的 `python -m backend.cli --live`；均须同时满足本批授权和预算。

### 4.1 运行环境：Windows 兼容（硬性要求）

项目在 **Windows** 上由 Codex 执行，所有代码、脚本、命令必须在 Windows 原生（PowerShell）下可用，同时不破坏 macOS / Linux。

- **不用** Makefile、`.sh` 脚本、bash 语法（`&&` 之外的管道技巧、`export`、`$(...)`）。任务脚本一律用 Python 写。
- 路径用 `pathlib.Path`，不拼接 `/` 或 `\\` 字符串；不硬编码盘符和绝对路径。
- **文件读写必须显式 `encoding="utf-8"`**（Windows 默认是 cp936 / cp932，会把中文、日文读写成乱码）。`scripts/dev.py` 启动时设置 `PYTHONUTF8=1`，子进程继承。
- 换行统一 LF（`.gitattributes` 已约束）；不提交 CRLF。
- 环境变量在 `scripts/dev.py` 内设置，不要求用户在 shell 里 `export`。
- 不依赖符号链接、`chmod`、`/tmp`。临时文件用 `tempfile`。
- Docker 使用 Docker Desktop（WSL2 后端）。涉及 `docker compose` 的任务，启动前先检查 Docker 是否在运行，没运行就在 `docs/blocked/environment.md` 记录并跳过，不要卡住。
- 拉取 DataMind 需要用户的 GitHub 凭据；拉取失败不是致命错误（见 M0.1）。

## 5. 密钥、费用与安全

- 密钥只从环境变量读取（`.env` 本地文件，已在 `.gitignore`）；提交 `.env.example`，只写变量名不写值。
- 绝不把密钥写进代码、测试、日志、trace 或文档。
- 真实模型调用必须按计费来源分开检查每日预算：DeepSeek 使用 `DAILY_BUDGET_CNY`（人民币元）；Anthropic/OpenAI 共用 `DAILY_BUDGET_USD`（美元）。两个币种独立记账，不自动换汇、相加或借用余额；使用兼容 SDK 不改变计费来源。
- 预算未配置、空白、非法或币种不匹配时拒绝真实调用；`0` 禁用对应线路，余额不足或达到上限即停止。预算值不代表调用授权，默认离线和用户本批次数限制仍需同时满足。
- `vendor/` 已在 `.gitignore`。其中 DataMind 是组织内部仓库，**任何内容都不能提交到本仓库**（本仓库是公开的）；评测用例改编后的版本可以提交，原文件不行。
- 日志在 INFO 级别不输出完整 prompt 和工具结果。SDK 会话文件属于私有运行数据，不进 Git 或公共 Trace。
- SDK 的 max_turns 不等于 HTTP 请求上限，max_budget_usd 不能代替人民币预算。新 SDK live 实验先证明费用/次数边界，再按本批授权运行，调用额度以 docs/execution/travel-agent.md 最新用户授权为准；旧两请求许可已用完，不能与本轮授权混淆。
