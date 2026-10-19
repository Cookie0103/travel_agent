# 2026-10-18 功能完整性对抗性审查

范围：整个 Travel Agent（后端、前端、数据库、Agent 运行时、部署）。目的：不因“页面存在”或“测试通过”判定完整，而是追踪 前端调用 → API → 服务 → 数据库 → 供应商 的真实链路，并给出可复现的失败用例。
对应批次计划：[2026-10-18 完整性加固](../../plans/2026-10-18-completeness-hardening.md)（任务状态与修复过程在那里；本文只记录**发现了什么**）。

## 1. 方法与可信度

| 阶段 | 做法 | 能证明什么 | 不能证明什么 |
| --- | --- | --- | --- |
| 清单 | 读设计文档（design/01–05、plans）与代码，整理 34 个端点、4 个页面、21 张表、18 个工具 | 功能边界 | 实现是否正确 |
| 审查 | 6 个独立只读 Agent，按域分工：会话/Run/SSE；旅行条件/攻略/记忆；行程规划；酒店预订；Agent 运行时/工具/MCP/预算；前端契约/部署/分层 | 代码路径、设计不一致 | 首轮 PostgreSQL 未启动，全部是静态结论（**REASONED**） |
| 复现 | 启动 PG 后，另一个验证 Agent 逐条写测试复现，标 CONFIRMED / REFUTED | 缺陷真实存在 | 真实模型被诱导的概率 |
| 遗漏查找 | 另一个验证 Agent：对照设计找缺失功能；HTTP 端到端走流程；迁移与模型 `compare_metadata`；对 13 处被测逻辑做变异检查测试能否失败 | 测试有效性 | 浏览器里的页面渲染（当时前端依赖缺失） |

结论标注沿用 [plans/README §3](../../plans/README.md)：**VERIFIED**＝运行复现；**REASONED**＝读代码推断；**ASSUMED**＝未核实。

整体结论：离线模式下端到端业务流程（登录→建行程→条件→酒店比较→草稿→确认→改程→暂留→订单）能走通，**没有 P0**；发现 5 个 P1 与一批 P2。已排除的误报见 §5。

## 2. 基线（审查时，未修改任何代码）

| 检查 | 结果 |
| --- | --- |
| tests/integration（真实 PG，临时库） | 447 通过 / 8 失败（首次因 pytest 临时目录权限出现 70 个 ERROR，非代码问题） |
| 8 个失败的根因 | 4 个：Windows 默认 Proactor 事件循环与 psycopg 不兼容（测试用 `asyncio.Runner()`，`scripts/export_history.py` 用 `asyncio.run`），属测试/脚本的平台缺陷；4 个：本机 Claude CLI 2.1.302 不在版本白名单（`runtime.py:96-103`），被有意拦截，环境漂移 |
| 前端 web-check | 类型/lint/格式、153 个测试、生产构建全通过；但这些测试只覆盖 `lib` 纯函数，不能证明页面可渲染 |
| import-linter | 3 条契约通过，但覆盖面窄（见 F4） |
| 迁移 | `upgrade head` 与 `Base.metadata` 的 `compare_metadata` 差异为 0；`downgrade base` 在 0004 失败 |

## 3. 发现清单

编号 = 工作包字母 + 序号，与批次计划任务一一对应。状态列在修复后更新（`open`＝未修；`fixed`＝已修并有回归测试；`decision`＝需用户决定；`wontfix`＝有理由不修）。

### P1

| ID | 问题 | 证据 | 复现状态 | 状态 |
| --- | --- | --- | --- | --- |
| A1 | 事件落库或 finish 失败后 Run 永远 `running`：同会话再发消息一直 409，取消无效，`GET /runs/{id}` 恒 503，只有重启 API 才恢复 | `services/runs.py:415-421, 487-514` | **VERIFIED**（monkeypatch 注入，数据库恢复后状态仍 running） | fixed |
| B1 | 用户已确认、进程在“confirmed 提交后、发 order 前”崩溃，订单永不补发，hold 过期后变 `failed`——用户确认过却从没下过单 | `services/bookings.py:165,176-177,244-249` | **VERIFIED**（崩溃用 monkeypatch 模拟） | fixed |
| B2 | 重复预订：同会话同日期可订两家不同酒店都 `booked`；同一酒店重新搜索（新 offer/evidence）可再 hold+order，得到 2 个订单 | `models.py:239` 唯一键仅 (session_id, evidence_id)；`bookings.py` 不检查日期重叠 | **VERIFIED**（2 booking / 2 hold / 2 order） | fixed |
| C1 | `PATCH /preferences` 把没改动的、已确认的对话事实重写成 `manual`，`evidence_quote` 为空（前端每次提交整个数组） | `services/preferences.py:99-137`、`preferences.tsx:92-100` | **VERIFIED**（旧行 superseded，新增 `寺庙 active manual ''`） | fixed |
| D2 | 锁定接口“版本过期”校验没有任何测试保护：去掉 `services/plans.py:394` 的判断，39 个相关集成测试仍全过 | 变异 M13 存活；`test_plans.py:843` 用随机 uuid 且裸 `pytest.raises(ServiceError)` | **VERIFIED**（变异） | fixed |
| E1 | `update_travel_request` 的 `explicit_fields` 由模型自填，声明后绕过用户手填字段的来源保护；服务端不核对新值是否出现在用户原话里，攻略/供应商文本可诱导模型改城市、日期、人数 | `tools/travel.py:160-172`、`services/travel.py:449-453,517-521` | 机制 **VERIFIED**（city 京都→大阪）；被注入诱导的概率 ASSUMED | fixed |

### P2

| ID | 问题 | 证据 | 复现状态 | 状态 |
| --- | --- | --- | --- | --- |
| A2 | SSE 每连接约 8+ 条 SQL/秒（0.25s 轮询） | `api/events.py:25-34` | REASONED | fixed |
| A3 | 前端把 SSE 流的正常结束当作 Run 结束，不查状态不重连；点“停止”后 UI 立即解除忙碌，再发 409 | `use-workspace.ts:190-275, 931-939` | REASONED（代理是否表现为干净 EOF 未实测；`docs/operations/product-v2.md:257` 记录过 45s socket hang up） | fixed |
| A4 | `ApiError` 丢掉后端 `code`；409 不自动刷新；FastAPI 自带 422 `{detail:[...]}` 无可读文案；`/models` 失败静默降级成 offline | `api.ts:30`、`models.ts:28` | REASONED | fixed |
| A5 | 登录成功后创建会话失败会留孤儿用户 | `use-workspace.ts:463-472` | REASONED | partial |
| B3 | `transition()` 状态未变时丢弃新 `error_code`；`quoted` 永不过期仍注入模型上下文；429/任意非 409 的 4xx 把报价永久标 failed（429 是有意设计，见决策 D4）；HTTP 与工具路径对 live/synthetic 报价状态码不一致（422/403）；预订按 JSON 时间戳**字符串**排序（`persistence/bookings.py:38`），曾出现 1 次偶发失败；前端币种符号写死 `¥` | `domain/booking.py:379`、`services/travel.py:185-190`、`bookings.py:50,101-103`、`bookings.tsx:49` | 多为 REASONED；排序偶发 1 次未稳定复现 | partial |
| C2 | 文本含 `\u0000` 时 `PATCH /preferences` 与 `PATCH /sessions/{id}/request` 返回 503“数据库暂不可用”而不是 422 | `services/common.py:67-75` | **VERIFIED**（DataError 22P05） | fixed |
| C3 | 日期/规模无上限：接受 1900-01-01～9999-12-31、120 晚、2 成人订 5 间房（HTTP 200） | `domain/travel_request.py:284-285`，下游 `services/plans.py:121` 逐日展开 | **VERIFIED**（接口层）；下游影响 REASONED | fixed |
| C4 | `GET /sessions/{id}/request` 有写副作用（新会话 GET 后 `travel_requests` 从 0 行变 1 行）并 `FOR UPDATE` 锁会话；`GET /choices/{id}` 同样锁会话 | `persistence/travel.py:18-26` | **VERIFIED** | fixed |
| C5 | 偏好面板在 Run 状态变化时覆盖未保存输入；其他会话事实显示“生效”却放在“历史版本”；“清除偏好”无二次确认；攻略页硬编码“京都·历史快照”“Wikivoyage”；时间展示不统一（原始 ISO / 未指定时区）；`/models` 不看当日预算 | `trip-panel.tsx:211`、`preferences.tsx:49,189,192,213-218,283-290`、`articles.tsx:16-17,35,48` | REASONED（静态） | partial |
| C6 | 画像生成同一 revision 并发各调一次 LLM；`source_turn_id` 写入不存在的随机 uuid 且无读取方；catalog 导入只 upsert，快照里删掉的条目永久残留 | `services/user_profile.py:116-158`、`domain/execution.py:154`、`persistence/catalog.py:231-251` | REASONED | fixed |
| D1 | 草稿过期后用相同参数重新暂存抛 409 `draft_expired`（幂等键只取决于输入）。**影响比最初估计小**：重新查询会产生新 `evidence_id`，正常流程可恢复，只有复用旧 `evidence_id` 才卡住 | `services/plans.py:183-194`、`persistence/operations.py:27` | **部分 VERIFIED**（11 分钟后重放 409；重新查询 evidence 变化 False→可生成） | fixed |
| D3 | 修复算子 `shifts()` 的“锁定项不能移动”守卫无测试（变异 M9 存活）；`settle` 在 drops/moves 后重建紧随其后锁定项的 `route_evidence_id` 时不检查 locked；repair 可能改动用户没动的旧冲突项（与 R07 有张力） | `domain/repair.py:249-270` | M9 **VERIFIED**；其余 REASONED | fixed |
| D4 | 加锁使正式版本 +1，待确认草稿随即 409 | `services/plans.py:413-420` | **VERIFIED**（HTTP） | fixed |
| D5 | `get_saved_plan` 的 items_only 不带 `locked`，“不存在”与“被锁定”合并为同一条 422；`LockInput` 校验失败走 FastAPI 默认格式而非 `{code,message}`；确认过期草稿的 409 不带 `draft_expired`；首次暂存冲突会残留空 `PlanRow`；`differences()` 看不到纯顺序变化 | `tools/travel.py:968-975`、`services/plans.py:216-233, 296-297`、`app.py:81-85`、`domain/plans.py:241-253` | REASONED | fixed |
| D6 | 单城市请求（无 segments）不检查景点停留时长 | `validator.py:272` | REASONED；设计意图未定 | decision |
| D7 | ics 无 `SEQUENCE`、不导出酒店、证据过期仍照常导出且不提示；前端下载文件名写死 `trip.ics`，对象 URL 立即 revoke | `services/calendar.py`、`calendar-button.tsx` | 导出功能本身 **VERIFIED 正常**（200、2 个 VEVENT、无身份 401）；其余 REASONED | fixed |
| E2 | 围栏按字段名白名单且只处理顶层集合行，`category`、`source.attribution`、`opening_hours`、`article.title/text` 等自由文本漏围栏 | `tools/fencing.py:325-377` | **部分 VERIFIED**（category、source.attribution 实测未围栏；opening_hours 样本为空未测） | fixed |
| E3 | 对外只读 MCP 返回无围栏；每次调用新建执行器（`max_calls` 形同虚设）；每次全量加载 catalog 并写 evidence | `mcp/server.py:547,554` | REASONED | fixed |
| E4 | Google/乐天 key 被放进 worker 环境，CLI 子进程继承 | `providers/claude_agent/environment.py:40-43` | REASONED（可利用路径未发现） | fixed |
| E5 | 写工具已提交后，序列化/超长失败仍被报成未发生，模型会重试；运行时 `assert` 在 `python -O` 下失效；`ToolDefinition.kind` 只是标签，外部 MCP 只读集合是手写名单 | `bridge.py:416-426`、`tools/travel.py:531-547`、`server.py:460-464` | REASONED | fixed |
| E6 | `/demo/login` 无速率限制，公网开启 DEMO_MODE 可无限建用户；令牌有效期文档写 24 小时、代码默认 30 天 | `services/sessions.py:37,46,61` | REASONED | fixed |
| F1 | Windows 默认 Proactor 事件循环与 psycopg 不兼容：3 个测试用 `asyncio.Runner()`、`scripts/export_history.py` 用 `asyncio.run`（脚本在 Windows 上真实不可用） | `export_history.py:41`、`test_synthetic_data.py:91` 等 | **VERIFIED**（换 Selector 循环后通过） | fixed |
| F2 | pytest 默认临时目录在本机 PermissionError，开箱即红 | — | **VERIFIED** | fixed |
| F3 | `/health` 只做 `SELECT 1`：库未迁移也报健康 | `persistence/sessions.py:12-13` | REASONED | fixed |
| F4 | import-linter 只有 3 条契约，实际存在未受保护的循环依赖（services↔tools、services↔providers/agent、adapters→persistence、eval→backend 46 处）；`ARCHITECTURE.md` 写“分层受保护”与实际不符 | `services/runs.py:17-18,37,42-43`、`tools/travel.py:37-45` 等 | **VERIFIED**（grep 与 lint-imports） | fixed |
| F5 | CLI 版本白名单（2.1.114/294/295）不含本机 2.1.302，4 个评测变体测试 blocked，错误信息不可诊断 | `runtime.py:96-103` | **VERIFIED**（原因）；换版本后是否通过未实测 | partial |
| G1 | 没有迁移与 models 的自动一致性测试 | — | 静态/一次性比较差异为 0，但无持续保护 | fixed |
| G2 | 21 张表没有任何 CHECK 约束；预订状态藏在 `bookings.payload` JSONB | `omit/migrate_compare.py` 输出 | **VERIFIED** | fixed |
| G3 | 初审认为若干按 `user_id` 查询的列无索引。**修复时逐条核对，只有 `task_runs(session_id, created_at)` 成立**；`task_runs.user_id`、`evidence.user_id/kind`、`bookings.user_id`、`plan_drafts.user_id`、`user_memory_facts.session_id` 的查询总是和 `session_id` 索引、主键或已有 `(user_id,status,key)` 联用，EXPLAIN 证实走现有索引，不加（初审判断有误） | `persistence/history.py:37,80`、`runs.py:76,117`、`travel.py:134-183` | 复合索引缺失 **VERIFIED**；7 万行 EXPLAIN：`run_page` 1.49ms→0.03ms，每会话仅约 10 次运行时无差别 | fixed |
| G4 | 迁移 `downgrade base` 在 0004 失败（后加外键未先删） | `fk_user_memory_facts_source_run_id_task_runs` | **VERIFIED** | wontfix |
| G5 | `travel_requests.source_turn_id` 只写不读（初审说“写入不存在的随机 uuid”**只对 HTTP 路径成立**：工具路径写真实 `run_id`，HTTP PATCH 用默认构造的 `RunContext`，其 `run_id` 是随机 uuid）；旧列 `users.preferences` 已废弃，仅供 0018 回退 | `persistence/travel.py:23,62`、`domain/execution.py:154` | **VERIFIED**（grep）；迁移只做加法，本轮不改列，处理建议见批次计划 | wontfix |

### 需要用户决定（不擅自实现）

| ID | 问题 | 现状 |
| --- | --- | --- |
| E7 | 实时模型调用没有按用户的额度/限流，预算与独占锁都是全局的；HUMAN 档位下 `DAILY_BUDGET_CNY` 完全不起作用（与设计文档“不足则拒绝”不符）；`UNCAPPED_CNY_DAY="2026-10-04"` 是已过期的硬编码例外 | `runs.py:178`、`budget.py:20,71` |
| G6 | 无会话/账户删除能力，无数据保留策略（`.env.example:25` 写了保留天数但无任何实现）；外键无 ON DELETE 策略 | 见批次计划待决事项 |

### P3 / 备注

- 对外 MCP、`GET /memory/{id}`、`GET /bookings/{id}` 前端未使用（冗余 API 面）。
- `DELETE /preferences`、`DELETE /memory/{id}` 带 JSON body，部分网关会丢弃 body；本地 TestClient 与浏览器 fetch 通过，仅提醒。
- 单条删除记忆也会前移全局“召回边界”（整段旧对话不再注入），疑似有意的保守设计，产品是否接受需确认；界面文案“这条偏好已删除”可能让用户以为连聊天原文也删了（聊天原文保留是批次决定 D1）。
- 61 处裸 `pytest.raises(ServiceError)` 没有断言错误码；`tests/test_evidence_ttl.py:90` 没有任何 assert；过度 mock 集中处：`test_upstream_stall.py`（34）、`test_claude_runtime.py`（24）、`test_live_application.py`（22）。
- `docs` 过期：`PROJECT_STATUS.md` 仍写“到期 hold 未修入主代码”，实际已由提交 9db5702 修复；`evaluation.md`、`QUALITY_SCORE.md` 未跟上新评测批次。

## 4. 变异检查（测试是否真能失败）

对 13 处被测逻辑人为破坏后重跑对应测试：10 处被现有测试抓住（确认接受硬冲突草稿、忽略 base_version、忽略草稿过期、确认不幂等、过期 hold 仍可确认、忽略 revision 变化、把 unknown 当失败、营业时间永不关闭、记忆读取忽略所有者、遗忘保留原文）；**存活 2 处** = D2（锁版本）、D3（`shifts` 锁定守卫）；另有 1 处 `persistence/plans.py` 的 user 过滤被去掉后仍通过，但上层 `owned_request` 还有第二层校验，判为等价变异，不计缺陷。

## 5. 已排除的误报（REFUTED）

| 初始说法 | 排除依据 |
| --- | --- |
| ~~并发两个 `confirm`，第二个会拿到 `unknown`~~ **（此条“排除”结论后被推翻）** | 初次验证 2 路并发 16 轮全部 `booked/booked`，但供应商响应是即时的。修复 B 时给 `supplier.order` 加 0.4 秒延迟、3 个并发 `confirm`，**复现了 `['booked','unknown','unknown']`**：order 在途时，第二个 `confirm` 进入 `reconcile` 查不到订单而落 `unknown`。已在 B4 修复（`test_concurrent_confirm_never_exposes_unknown_while_order_is_in_flight`）。教训：并发类结论必须在慢依赖下复现，同步 fake 下的“未复现”不算排除 |
| ics 导出可能有问题 | HTTP 实测 200、`BEGIN:VCALENDAR`、2 个 VEVENT、无身份 401；UTC 时间、转义、按字节折行均符合 RFC 5545（只验证基本结构） |
| 到期 hold 重复返回仍为 held（PROJECT_STATUS P0-1） | 主代码已修复（提交 9db5702，`Booking.hold_expired`） |
| 越权访问他人资源 | 所有他人 session/run/booking/draft/plan/fact 访问一律 404，已有测试覆盖 |

## 6. 未覆盖（诚实说明）

- 首轮审查时前端依赖缺失，**未做浏览器端到端**；修复阶段补做（见批次计划 §9）。
- 未调用任何付费模型：真实模型被提示注入诱导的概率、live 模式下的行为均未测。
- 容器演示栈（Docker Compose demo）未验证。
- 多进程并发下的预订竞态未测。
