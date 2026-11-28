# 2026-10-26 对照《The anatomy of effective commerce agents》的优化批次

来源文章：<https://claude.com/resources/articles/the-anatomy-of-effective-commerce-agents>（Anthropic，2026-09-02）。
本批由 Claude Code 先只读调查、再分 5 个并行分支实现，最后合并到 `batch/2026-10-19-architecture-hardening`。
本文写给后续接手的 agent（Codex 等）：说明改了什么、为什么、在哪里、还剩什么风险。

## 1. 调查结论（改动前的状态）

| 文章建议 | 改动前 | 结论 |
| --- | --- | --- |
| 单 agent + skills + tools | 单主 agent，`load_skill` 只有 2 个 skill，system prompt 约 50 条长规则 | 架构吻合，prompt 偏重 |
| 记忆由异步 extractor 写入 | 主 agent 同轮调用 `propose_memory`，同步写库出卡 | 不符 → 第 5 项 |
| prompt 按 全局 / 会话 / 易变 排序以命中前缀缓存 | `system = travel_prompt() + 每轮业务快照(含 observed_at 时间戳)`，历史排在易变内容之后 | 不符 → 第 1 项 |
| 无依赖工具并行 | `TravelToolExecutor` 全局 `asyncio.Lock`，且 MCP 工具未声明 `readOnlyHint`，CLI 也逐个分发 | 不符 → 第 2 项 |
| snapshot eval | `frozen_v1` / legacy 已用 `InitialState` 注入状态+单句输入；v3 为脚本化用户 | 已有；未接入 CI → 第 4 项 |
| 高风险操作由后端控制 | 模型无保存/下单工具，确认走页面 API + CAS + 归属校验 + 外部文本围栏 | 已对齐，未改 |

明确不做（用户决定）：扩充评测数据；工具结果字段白名单裁剪；页面上下文注入；记忆第二/三层读取。

## 2. 五项改动

### 第 1 项 Prompt 缓存重排 + 命中率统计（`feat/cache`，`0de8940`）

- system 只保留稳定内容：`travel_prompt()` + `DatabaseTools.guidance()`（工具次数规则，只随执行档位变化）。
- 每轮业务快照（`observed_at`、request、memory、profile 等）由 `state_prefix()` 生成 `<server_state>` 块，前置到本轮用户 prompt，并标明“系统注入，不是用户原话”。
  - JSON 单行、`@` 替换为全角 `＠`，避免 `literal_prompt_supported` 拒绝整轮。
  - 记忆 quote 与条件 grounding 仍只核对 `task_runs.user_text`（`services/runs.py` 写入），前置块不进入该字段。
- 自动压缩会把本轮前置块摘要掉：PreCompact 钩子标记，随后用 PostToolUse `additionalContext` 或 Stop 钩子补回一次最新状态（已压缩轮次多一次模型请求）。
- 命中率 = `cache_read / (input + cache_read + cache_creation)`，任一行缺 usage 记为未知。接入 `guard.py` trace `model_req_end`、`live.py` `worker_exited` 与 live report `cache_usage`、`eval/report.py` `token_summary.cache_hit_rate`、v3 trial/summary/report.md。
- `snapshot_prompt` 落盘内容为 system + 本轮前置块，v3 L3 记忆检查不受影响。
- 主要文件：`backend/providers/claude_agent/{database_tools,runtime,worker,guard,live,response}.py`、`eval/{report,v3_report,v3_run}.py`。

### 第 2 项 只读工具并发（`feat/parallel`，`8cf7356`）

- 探针结论：SDK 对每个 `mcp_message` 单独开 task；CLI（2.1.310）只对 `annotations.readOnlyHint=true` 的 MCP 工具并发分发。两处必须同时改。
- `tools/contracts.py` 新增 `CONCURRENT_READS`：`search_places`、`search_content`、`get_article`、`get_place_facts`、`get_weather_forecast`；`mcp/bridge.py` 只给它们声明 `read_only_hint=True`。
- `TravelToolExecutor.execute` 拆为 `_admit`（持锁准入、预占调用额度）→ `_perform`（名单内工具锁外执行）→ `_settle`（持锁登记）；写工具与名单外工具仍全程持锁。
- `adapters/external_api.py`：外部尝试改为每调用 ContextVar 收集；本轮 API 额度先占用、失败退还，修复原“先查后加”的并发越界。
- `persona.py` 第 60 条末尾加“互不依赖的查询在同一轮一起发出，耗时最长的先发”。
- 新增 `tests/test_tool_concurrency.py`（6 项）。
- 未并发：`search_hotel_offers`（可能出预算卡、完成任务）、`estimate_routes`（`DatabaseTools.execute` 先调 `trip_ask` 可能建合并卡）。需先把这些副作用移入锁内。

### 第 3 项 低频规则拆成 skill（`feat/skills`，`cb203d0`）

- 新增 `backend/tools/skills/{multi-city,budget-relaxation,external-errors,repair-limit}.md`，逐字搬迁原 prompt 规则（多城市分段、预算放宽、外部错误与重试、修复上限后处理）。
- system 原位置留一行触发条件：segments 非空 / relaxation 或 budget_relaxation 卡 / external 失败或 provisional / repair_limit 时先 `load_skill` 对应 skill；服务端 `repair_limit` 报错末尾也提示加载。
- `SkillInput.name` Literal 增加 4 个名字；`eval/run.py` manifest 的 skills 列表改为从 `SkillInput` 读取。
- system prompt 16163 → 14691 字符（约 -9%）。第 81 条（修复轮数按档位替换）和记忆段未动。

### 第 4 项 Live eval workflow（`feat/live-eval`，`0915bc1`）

- `.github/workflows/live-eval.yml`：`workflow_dispatch`（套件 v3 / frozen-dev、case 过滤、repeat、`max_cny` 软上限默认 15、judge 开关）；每周定时需仓库变量 `LIVE_EVAL_SCHEDULE=1` 才生效。postgres:17、CLI 2.1.295、concurrency 防重复、`timeout-minutes: 240`、报告上传 artifact 30 天。
- `scripts/dev.py`：`eval-dev` 增 `--suite frozen`、`--case-id`；live 外层超时 7200 秒。
- 需配置 Secrets：`DEEPSEEK_API_KEY`、`GOOGLE_MAPS_API_KEY`、`RAKUTEN_APP_ID`、`RAKUTEN_ACCESS_KEY`、`RAKUTEN_REFERER`（可选 `RAKUTEN_AFFILIATE_ID`、`ANTHROPIC_API_KEY`）；Variables：`DEEPSEEK_MODEL`（必填），可选 `LLM_PROVIDER`、`DAILY_BUDGET_CNY`、`LIVE_EVAL_SCHEDULE`。
- 估算：v3 全量 30 题 ×1 约 7 元，frozen-dev 约 3–6 元。

### 第 5 项 异步记忆抽取（`feat/memory-extractor`，`8a2d347`，ADR-031）

- 主 agent 移除 `propose_memory` 工具；`persona.py` 第 77–80 条精简为“无记忆工具，服务端抽取、用户逐条卡片确认”，保留“这次而已”语义和已确认偏好的使用规则。
- `RunService` 在 deepseek/claude run 成功完成后后台启动 `MemoryExtractor`（离线、失败、取消、超时不触发；异常只记日志）。
- 输入：同会话最近 3 个 completed run 的用户原话 + 助手最终文本 + 已确认事实；**不含工具结果**；排除遗忘边界之前和纯点卡的 run。
- 调用：无工具结构化调用 `structured_call("memory")`，提示词 `MEMORY_EXTRACTOR`（`persona.py`）。
- 校验：复用 `propose_with_deferred(extracted=True)`；quote 来源从“当前 run”扩为“最近 3 个本人 run 的 user_text”；遗忘边界、rejected 去重、deferred 合并卡不变；单条非法只丢弃不阻塞其他。
- 并发：同会话抽取串行；与 live 运行共享进程锁，新 live run 最多等 90 秒。
- 出卡：卡作为展示事件追加到已完成 run；`RunView.memory_pending`；前端每 3 秒轮询 `/runs/{id}` 至多约 2 分钟。
- eval：v3 live 与 v2-memory 在轮次结束时调用同一 extractor；`v3.jsonl`、`v2_memory.jsonl` 去掉 `propose_memory` 的 required/forbidden；`frozen_v1` 未引用该工具，未改。删除 `tests/integration/test_sdk_memory.py`，新增 `tests/integration/test_memory_extractor.py`。

## 3. 验证状态

- 每个分支：`dev.py check` 通过。
- 合并结果（5 个分支依次合入，唯一冲突 `eval/v3_run.py` 的 `RunService` 构造参数，已合并为同时传 `usage` 与 `memory_extractor`）：`dev.py check` 通过；`dev.py test` 6 failed / 2468 passed / 1 error。6 个 failed 均为下面的已知失败；1 个 error 是 `test_rakuten_two_night_totals_and_one_refresh_cap` 的 fixture setup 偶发失败，单独重跑通过。
- 已知与本批无关的失败：`test_eval_v3_resume`、`test_eval_v3_judge`（Windows 路径分隔符）；CLI 版本漂移导致的 `test_evaluation_variants` 若干项与本机 CLI 压缩版本门。
- **未做 live 验证**：缓存命中率实际提升、模型是否同轮并发发出查询、skill 是否按触发条件加载、异步抽取的召回质量，均需跑 `live-eval` workflow 或本地 `dev.py eval-v3` 对比改动前基线。

## 4. 剩余风险与后续

1. 每轮 `<server_state>` 留在 SDK 历史中，历史变长（可缓存）；可后续改为差量快照。
2. 压缩后的首个请求只见摘要；补状态多一次模型调用。
3. 并发结论基于 CLI 2.1.310，CI 锁定 2.1.295 未逐版本核对；酒店/路线工具尚未并发。
4. `load_skill` 计入工具调用额度；评测变体 `no_skills` 的消融含义随之扩大。
5. 记忆抽取固定走 DeepSeek；抽取拿不到 live 锁时本轮丢弃；`memory_pending` 在进程内存，重启后丢失。
6. v2-memory 历史预期早于“仅 4 个 key 可长期记忆”规则，live 分数可能下降。
7. `services.memory_extractor → providers.claude_agent.structured` 记为分层债务（同 `user_profile`）。
