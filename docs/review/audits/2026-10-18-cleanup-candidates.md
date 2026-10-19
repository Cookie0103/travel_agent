# 可清理代码核查（只读，未删除任何东西）

核查日期 2026-10-18。方法：python ast + `git grep` 自写扫描（vulture 未安装）；方法级扫描按名字匹配，同名方法会互相遮蔽，结论是**下限**，没抓到不等于没有；没有覆盖率数据。上一轮 code-slimming（[archive](../../archive/review/cursor/2026-10-11-code-slimming/README.md)）已清过一遍，所以后端整体比较干净：完全无引用的顶层函数/类/常量只有 3 个。

本文列出**可以清理的候选**与风险，供你决定；批次计划的待决项见 [D15](../../plans/2026-10-18-completeness-hardening.md)。

## 一、建议删除（低风险）

| # | 路径 | 证据 | 风险 | 可减行数 |
| --- | --- | --- | --- | --- |
| 1 | `.cache/`（约 1.3GB，已被 `.gitignore`） | 内有 `expiry-fix-20261004/`（整份旧代码副本）、`pytest-*` 一次性目录、几十个 `v2-*.py` 与 `verification-sweep-*.py` 一次性脚本、`.log`。**`uv/`、`python/`、`pnpm/`、`pre-commit/` 缓存要留**，否则要重新下载；旧文档可能把部分证据 json 当原始证据引用 | 低 | 磁盘约 1GB，不算代码行 |
| 2 | `backend/providers/probe/`、`backend/providers/sdk_probe/` | 目录里只剩 `__pycache__/*.pyc`，没有任何被 git 跟踪的文件；`PROJECT_STATUS.md` 写明已并入 `claude_agent` | 无 | 删两个空壳目录 |
| 3 | `UNCAPPED_CNY_DAY = "2026-10-04"`（`providers/claude_agent/budget.py:20, 71-72`） | 写死的“仅今日暂停日限”豁免日，今天已过，分支永远不会再走到；注释还写着“今日”。属费用逻辑 | 极低（但属费用核心代码，请你确认） | 约 4 |
| 4 | `MAX_INPUT_TOKENS`（`providers/claude_agent/request.py:13`） | 全仓无任何引用 | 无 | 1 |
| 5 | `scripts/dev.py:121-129` 的 `eval_dev` 里“eval.run 尚未实现，等待 M0.6”守卫 | `eval/run.py` 早已存在，这个 if 永远为假 | 极低 | 约 4 |
| 6 | `apps/web/src/lib/models.ts:14-21` 的 `modeLabel` | 前端 src 与 tests 都没有引用 | 无 | 8 |
| 7 | 前端多余的 `export`（`activityEntries`、`toolCallCount`、`ChoiceGroup`、`isRunActive`、`PACE_PREFIX` 等） | 只在文件内部使用；去掉 `export` 关键字即可，不是删代码 | 无 | 0（收窄导出） |
| 8 | `bookings.tsx:73-76` 内联的 `toLocaleString("zh-CN",{timeZone:"Asia/Tokyo"})` | 与 `lib/format-time.ts` 的 `formatTokyo` 重复；改用后输出多了补零、没有秒 | 低（显示格式微调） | 约 3 |

## 二、建议删除（需你确认）

| # | 路径 | 证据 | 风险 | 可减行数 |
| --- | --- | --- | --- | --- |
| 9 | `tests/fixtures/rakuten_{kyoto,sapporo,osaka}_*.json`，共 21 个文件约 2.3MB | 全仓代码与测试都不读它们；只有 `scripts/probe_hotel_coverage.py:170` 在跑真实调用时会生成这类文件，和 product-v2 计划把它们当证据描述。同目录的 `rakuten_naha_*` 被测试使用，要留 | 失去 ADR-016 的实测原始证据（文档仍引用）；建议先挪到 `docs/evidence/` 或 `.cache/` | 约 34,300（json） |
| 10 | `scripts/probe_hotel_coverage.py`（267 行）、`scripts/probe_plan_feedback.py`（265 行）及其测试 `tests/test_hotel_coverage_probe.py`（56）、`tests/test_plan_feedback_probe.py`（136） | 没接入 `dev.py`，CI 没引用，是 2026-10-09 的一次性真实调用探针；`probe_plan_feedback` 还重复了 `adapters/evaluation_faults.synthetic_places`。`probe_hotel_sort.py` 已接入 `dev probe-hotel-sort`，保留 | 删后无法重新实测乐天覆盖，但数据已落档；建议先归档 | 约 724 |
| 11 | `Ledger.charge` / `start_flow` / `append`（`providers/claude_agent/ledger.py:111-134`） | 生产只用 `Ledger.entries()` 读旧账；这 3 个写方法只被 `tests/test_protocol_probe.py` 与 `test_sdk_budget.py` 调用，“flow/success”账目是旧探针概念；上一轮 slimming 记过要删 | 要连带改 3 个测试；旧账本文件的读取要保留 | 生产约 30 + 测试约 30 |
| 12 | `ExternalApiUsageRow`、`GoogleCoordinateRow`（`persistence/models.py:67-81`） | 两个 ORM 类零引用；对应表只被原生 SQL 读写，迁移 0011 建表。**注意**：本轮新增的 `test_schema_consistency` 会比较模型与迁移，删类前必须同时处理，否则该测试会报 `remove_table` | 需配合一致性测试 | 12 |
| 13 | `anthropic` 依赖（`pyproject.toml:8`） | 全部 `.py` 没有 `import anthropic`；只有 `tests/test_architecture.py:57` 与 import-linter 契约把它当禁用模块名 | 属“移除依赖”，要走 ADR；去掉后重生成 `uv.lock`，更新 ADR-000/002/003 措辞 | pyproject 1 行 + lock 约 40 |
| 14 | `users.preferences` 旧列（`models.py:100`） | 只写入 `{}`，无读取；0018 的 `downgrade` 靠它回退并重建投影 | 需新迁移 `DROP COLUMN`，且要同时改 0018 的 downgrade 与 `test_memory_migration`；回滚会丢数据 | 约 5 + 一个迁移 |
| 15 | `travel_requests.source_turn_id` | 只写不读；唯一的读取是 `tests/integration/test_travel.py:331` 的断言 | 想保留审计用途就补文档；否则连同迁移删 | 约 4 + 1 个测试断言 |

## 三、建议保留，但需要处理

| # | 项 | 说明 |
| --- | --- | --- |
| 16 | `FORM_ROW_KINDS = ("form","travel_details")`（`domain/choices.py:19`；`services/choices.py:321`、`models.py:51`、迁移 0022 CHECK、`eval/simulator.py:471`） | 读取边界兼容层，库里可能还有旧 `travel_details` 卡；**不能直接删**，因为 0022 的 CHECK 约束包含它。清理需先写数据迁移把旧卡改成 `form`，再收紧 CHECK，然后一起删 `legacy_form`、`services/choices.py:321-329`、`ChoiceSelection.legacy_details`，合计约 55 行 |
| 17 | `TravelService.get_request()`（`services/travel.py:135`）仍走写锁路径 | 它用 `owned_request`（对会话 `FOR UPDATE` 并 `INSERT … ON CONFLICT DO NOTHING`），却被约 16 处纯读调用使用。本轮新增的只读 `read_request` 只给 `get_request_view` 用。**被本轮取代但没迁完**：纯读场景改用只读版才能彻底取消读路径的写锁 |
| 18 | `backend/providers/claude_agent/request.py:14` 的 `TOOL_NAME="mcp__probe__echo"`、`guard.py:47` 默认 allowed_tools | 探针时代遗留，但 `test_sdk_guard.py`、`test_sdk_cli_offline.py` 在用；要清理需连带改测试，优先级低 |
| 19 | `eval/assess.py`、`eval/structured.py`、eval 的 legacy / frozen 套件 | `assess.py` 是文档化的手动入口；`structured.py` 仅 3 行转发；legacy / frozen 套件被 `docs/evidence/*.json` 的哈希引用，是冻结证据，**不要动** |
| 20 | `legacy_request()`、`LegacyRequestSnapshot`、`LEGACY_DETAIL_FIELDS`、`tests/fixtures/legacy_*_v1.py` | 仍有生产调用（`conditions` 列、报价快照、验证器），是有意的双写，不是死代码 |
| 21 | 旧人民币账本归一化（`budget.py:68-73`）、`Budget.legacy` | 兼容磁盘上已有账本文件，保留 |
| 22 | 无断言测试 | 只有 `tests/test_evidence_ttl.py:90` 与 `tests/test_trace_log.py:69` 两个“不应抛错”型，可保留，建议补显式断言 |
| 23 | 裸 `pytest.raises(ServiceError)` 共 62 处 | 按文件：`integration/test_memory.py` 10；`test_travel.py` 6；`test_plans.py` 6；`test_planning.py` 4；`test_choices.py` 4；`test_tool_failure_detail.py`、`test_lodging_budget.py`、`test_hotels.py` 各 3；其余各 1–2。建议改成断言 `status`/`code`，不是删除 |
| 24 | `mcp`、`starlette` 被 `backend/mcp/server.py` 直接 import 却没在 `pyproject.toml` 声明 | 靠 `claude-agent-sdk` 的传递依赖；建议显式声明 |

## 四、不要动

- **API 端点**：34+1 个路由都有至少一个调用方。前端未用的 `GET /health`（Railway 健康检查、README、5 个测试）、`GET /bookings/{id}`（`scripts/smoke_demo.py` 与 CI 用）、`GET /memory/{fact_id}`（归属隔离测试覆盖，设计契约写入 `design/02`）、`GET /health/ready`（`docker-compose.demo.yml` 用）都是对外契约，保留。
- `mock_supplier` 的四种故障（`delay`、`rate_limit`、`server_error`、`lose_response`）都被测试或 eval 使用。
- `data/`、`vendor/`（只读）、`apps/web/src/lib/api-types.ts`（生成文件）。
- 前端依赖没有多余；除 `anthropic` 外的 Python 依赖都有直接 import。
- 前端只被测试使用的导出（`providerLabel`、`runStatus`、`loadModels`、`reconnectDelay` 等）属被测纯函数，保留。

## 五、文档与配置的差异（已核对）

文档里指向已不存在文件的描述：`PROJECT_STATUS.md:183` 写 `claude_agent/limits.py`（实际在 `backend/limits.py`）；`docs/design/05-validation.md` 提到不存在的 `eval/configs/`；`docs/design/06-sources.md` 提到不存在的 `docs/rurubu_andmore_feature_plan.md` 与 `eval/src/graders/`；`docs/protocols/protocol-agent-sdk.md` 与 `docs/tasks/M0.md` 提到不存在的 `tests/live/test_agent_sdk_integration.py`；`docs/tasks/M0.md` 还提到 `docs/journal.md`、`eval/cases/datamind_adapted.json`（实际是 `.jsonl`）、已删的 `backend/providers/sdk_probe/`。

与代码不符的陈述：`README.md:126` 写“/health 检查数据库”，现在 `/health` 只是存活检查，迁移与就绪由 `/health/ready` 管；`PROJECT_STATUS.md:11` 写“3 条分层契约”（现为 11 条；该文件是历史快照）。

`.env.example` 里的 27 个键代码全部有读取，没有多余键；**代码读取但 `.env.example` 没有的变量**：

| 变量 | 读取位置 | 作用 |
| --- | --- | --- |
| `TRAVEL_PROFILE` | `backend/profile.py:53` | 选 `relaxed`/`human` 档位，默认 DEFAULT |
| `MOCK_SUPPLIER_URL` | `adapters/supplier.py`、`claude_agent/live.py`、compose | 模拟供应商地址 |
| `TRAVEL_API_ORIGIN` | `apps/web/next.config.ts:3` | 前端代理的 API 地址，默认 `http://127.0.0.1:8000` |
| `DEMO_LOGIN_PER_IP`、`DEMO_LOGIN_GLOBAL`、`DEMO_LOGIN_WINDOW_SECONDS` | `services/sessions.py` | 演示登录限流（本轮新增） |
| `MCP_RATE_BURST`、`MCP_RATE_PER_SECOND` | `mcp/server.py` | 对外 MCP 限流（本轮新增） |
| `TRAVEL_CLAUDE_CLI` | `claude_agent/environment.py:18` | 指定 Claude CLI 路径 |
| `CLAUDE_CODE_GIT_BASH_PATH` | `claude_agent/environment.py:69,111` | Windows 下 Git Bash 路径 |
| `TRAVEL_TRACE_FILE`、`TRAVEL_TRACE_RUN` | `backend/trace_log.py:15` | 本地 trace 文件 |

开发脚本自己设置、不需要进示例：`PRE_COMMIT_HOME`、`PYTEST_DEBUG_TEMPROOT`、`UV_CACHE_DIR`、`PYTHONUTF8`、`PYTHONIOENCODING`。

## 六、总结

| 档位 | 项数 | 预计可减行数 |
| --- | --- | --- |
| 建议删除（低风险）1–8 | 8 | 约 20 行代码；另约 1GB 磁盘（`.cache`） |
| 建议删除（需确认）9–15 | 7 | 约 35,100 行：json 约 34,300，探针脚本与测试约 724，其余约 100 |
| 建议保留但需处理 16–24 | 9 | 若做第 16 项约 55 行，其余是重构或补测试，基本不减行 |

行数大头几乎都在第 9 项的 21 个 Rakuten 样本 json，不影响运行。**最值得先做的 3 件事**：第 17 项（读路径写锁迁完）、第 3/4/5 项（几行死代码）、第 23 项（裸 `pytest.raises` 改成断言错误码）。
（原核查报告里的第 16 项“失败的旧测试”已在本轮改写，见批次计划 P-A1。）
