# 2026-10-18 完整性加固（对抗性审查 + 修复）

本批次的发现清单见 [完整性审查报告](../review/audits/2026-10-18-completeness-audit.md)；本文维护**任务状态、决定、修复过程**（记录规则见 [plans/README](README.md)）。

## 1. 基本信息

- 开始：2026-10-18　分支：`batch/2026-10-15/latency-optimization`　基线 commit：`13e3c20`（工作区干净）
- 目标：不因“页面存在/测试通过”判完整；把审查找出的真实缺陷用先红后绿的测试修掉，把文档整理成可检索的结构，并保证以后的开发、测试、问题、修复都有地方记。
- done means：
  1. 审查报告中每个 P1 都有回归测试，且“去掉修复该测试会红”；
  2. 每个 P2 要么有回归测试，要么写明不修的理由或进入“待用户决定”；
  3. `dev check`、`dev test`（含真实 PG 集成）、`dev web-check` 全绿；Windows 上原来 8 个基线失败中 4 个平台缺陷转绿，4 个 CLI 版本问题有可诊断信息；
  4. 浏览器端到端走通一次（含刷新恢复与断流恢复）；
  5. 文档入口重整，所有链接可达。
- 不做：真实付费模型调用；会话/账户删除与数据保留策略（待决，见 §2）；按用户的 live 额度；不 push、不合并 main。

## 2. 待用户决定

| ID | 问题 | 推荐 | 不决定的影响 | 结论 |
| --- | --- | --- | --- | --- |
| D1 | **live 额度**：实时模型调用的预算与独占锁是全局的，公开部署任何访客可耗尽当日预算；HUMAN 档位 `DAILY_BUDGET_CNY` 不生效，与设计文档“不足则拒绝”不一致 | 先限制 `/demo/login` 频率（本批做），按用户额度另立批次 | 公开部署有被刷光预算的风险；本地使用无影响 | 待定 |
| D2 | **数据保留/删除**：无会话与账户删除，过期数据永不清理，`.env.example` 声称的保留天数未实现 | 先出方案（工作包 G6 报告），再选；涉及隐私与记忆“遗忘边界”语义 | 数据只增不减 | 待定 |
| D3 | **过去日期**是否允许出现在旅行条件里（本批实现：固定下限 2000-01-01 + 上限今天+3 年 + 最长 30 晚，不拒绝近期过去日期） | 允许但标注，避免现有评测/fixture 因时钟失效 | 用户可建立过去日期的行程 | **已决（2026-10-19）**：日期必须 ≥ 今天（东京），过去日期报错；上限今天+3 年不变。夹具用 `fixed_today` 钉住时钟 |
| D4 | **供应商 429**：现为“业务终态 failed，需重新报价”（`test_eval_state.py:303` 注明是有意设计）；瞬时限流也会烧掉报价 | 保持现状，除非有证据 | 瞬时限流体验差，但不会出错 | 待定 |
| D5 | **CLI 2.1.302 是否加入白名单**：白名单是安全边界，加入前需验证兼容；4 个评测变体测试因此 blocked | 不加；用 `dev doctor` 提示安装已验证版本；需要时先做兼容验证 | 本机 4 个评测变体测试保持 blocked | 待定 |
| D6 | **记忆遗忘语义**：单条删除也会前移全局“召回边界”；界面文案“这条偏好已删除”可能让用户以为聊天原文也被删 | 保持边界，改文案说明“聊天记录保留，仅不再用于推荐” | 用户可能误解 | 待定 |
| D7 | 单城市请求是否也检查景点停留时长 | 设计无明文，保持现状并记录 | 极端短停留不报警 | 待定 |
| D8 | **演示令牌有效期**：文档（ADR-006、`backend/api/README.md:4`、`README.md:128`）写 24 小时，代码默认 30 天（`DEMO_TOKEN_DAYS` 可配 1–365） | 以代码为准，改文档；公网部署显式设 `DEMO_TOKEN_DAYS=1` | 文档与代码持续不一致 | 待定 |
| D9 | 反向代理部署是否启用 uvicorn `--proxy-headers`（否则 `/demo/login` 的每 IP 限流退化为全局限流） | 公网部署启用 | 限流不精细，但仍有保护 | 待定 |
| D10 | **围栏/来源保护的误拒**：`explicit_fields` 现在需要在用户原话中找到出处，别名、方言、省略写法可能被误拒（后果只是被跳过、模型追问） | 接受；上线后观察 `skipped_fields` 比例再调规则 | 个别正常改动要多问一句 | 待定 |
| D11 | 日期/规模默认值：最长 30 晚、日期上限今天+3 年（下限固定 2000-01-01）、房间数 ≤ 总人数 | 采用 | 边界按需调整 | 待定 |
| D12 | **行程规划相关 5 项**（来自 WP-D）：① 加锁后待确认草稿是否改成“仅锁变化时合并”（现为明确报错重新生成）；② 是否在 `ToolReason`/`StageReason` 枚举新增 `patch_item_locked`、`plan_version_changed`（现归为 `other`，前端“已锁定”文案不精确，要改 `domain/execution.py`、重新生成 api-types、改前端两处文案）；③ 纯顺序变化要不要独立的 `op="move"`（要改 `results.tsx` 与契约）；④ repair 是否限制在 patch 触及的项（可能让草稿因旧冲突而无法确认）；⑤ 是否导出已订酒店的入住/退房 ics 事件 | ①④⑤保持现状，②③体量小可做 | 体验细节 | 待定 |
| D13 | `/models` 是否显示“今日预算已用尽”（需抽出 `budget.py` 的当日累计函数，改费用核心代码） | 做，但由负责预算的改动单独评审 | 界面显示可用、提交才 403 | 待定 |
| D14 | `source_turn_id` 列：保留并标“暂无读取方”／改名 `source_run_id` 加 FK／删除；`users.preferences` 旧列何时删 | 先文档化为遗留 | 无功能影响 | 待定 |
| D15 | `UNCAPPED_CNY_DAY="2026-10-04"` 已过期的硬编码日期例外（`budget.py:20,71`）是否删除 | 删（死代码），但属费用逻辑，请你确认后再动 | 无影响 | 待定 |

## 3. 评审与设计

- **方法**：6 个领域审查 Agent（只读）→ 2 个验证 Agent（复现 / 遗漏）→ 7 个修复工作包并行 → 独立对抗性复核（见 §9）。分工与文件边界：工作包只改自己的文件，`models.py`/`migrations/` 由 G 独占，`tools/travel.py` 由 D（plan 区域）与 E（`update_travel_request`、围栏）分区编辑。
- **修复准则**：先写能失败的测试并看它红，再修；不改断言、不跳过；沿用 [工程标准 §3.4](../execution/standards.md#34-sdk-优先与简洁复用)，不为假想扩展加抽象。
- **验证员对初审结论的更正**（保留在报告 §5）：并发确认返回 unknown 未复现；D1 草稿过期影响比预估小；ics 导出功能正常。

## 4. 任务表

状态含义见 [plans/README §3](README.md)。证据列在 `done` 时填 commit/测试数量；**当前尚未提交**，因此只写运行过的检查。

| 任务 | 关联发现 | 依赖 | 验收条件 | 状态 | 证据 |
| --- | --- | --- | --- | --- | --- |
| WP-A Run 生命周期与 SSE | A1 A2 A3 A4 A5 | — | 持久化失败后 Run 能在线恢复到终态并释放会话；流在终态前结束会按 sequence 重连；停止后不再 409 | done | 见 §8 对应 P-条目；检查结果见 §9 |
| WP-B 预订完整性 | B1 B2 B3 | — | 确认后崩溃可补发订单；同段同日期不得重复预订；币种格式化 | done | 见 §8 对应 P-条目；检查结果见 §9 |
| WP-C 条件校验与偏好记忆 | C1–C6 | — | 值不变的事实保持来源；NUL→422；日期/规模边界；GET 无写副作用；偏好面板不覆盖未保存输入 | done | 见 §8 对应 P-条目；检查结果见 §9 |
| WP-D 行程规划与日历 | D1–D7 | — | 过期草稿可重新生成；锁版本校验有测试；`shifts` 锁定守卫有测试；ics 有 HTTP 测试 | done | 见 §8 对应 P-条目；检查结果见 §9 |
| WP-E 工具层安全 | E1–E6 | — | explicit_fields 需出处核对；围栏默认覆盖全部自由文本；对外 MCP 围栏与限流；登录限流 | done | 见 §8 对应 P-条目；检查结果见 §9 |
| WP-F 平台与分层 | F1–F5 | — | Windows 下 4 个平台失败转绿；pytest 临时目录开箱可用；`/health/ready` 校验迁移；分层契约扩充并登记债务；`dev doctor` | done | 见 §8 对应 P-条目；检查结果见 §9 |
| WP-G 数据库约束 | G1–G6 | — | 迁移/模型一致性测试；CHECK 与索引迁移；downgrade 评估 | done | 见 §8 对应 P-条目；检查结果见 §9 |
| WP-H 文档整理 | — | — | 入口重写、历史归档、测试总览、批次索引、死链 0 | done | 见 §8 对应 P-条目；检查结果见 §9 |
| WP-I 浏览器端到端 | — | A–G | 登录→建行程→对话→草稿→确认→改程→暂留→订单；刷新与断流恢复 | done | 真 Chrome 走通；问题见 §8 P-R6 |
| WP-J 对抗性复核 | — | A–G | 独立 Agent 复攻各修复，复现原失败用例应全部消失，并尝试绕过 | done | 5 项被攻破并已修（§8 第二轮 P-R1–R5），9 项守住 |

## 5. 边界与不变量

- 模型没有正式保存/下单工具（`ARCHITECTURE.md`）：本批所有改动不得破坏，E5 的“写已提交即不报失败”不改变这一点。
- 迁移只做加法；不删列、不改旧迁移内容。
- 默认离线；本批不调用任何付费模型。
- 不 push、不合并 main、不改写历史（沿用 AGENTS.md）；本批改动在你确认后再提交。

## 6. 发布与回退

未提交。回退＝丢弃工作区改动或 revert 对应提交；新迁移只加法，回退需单独评估（见 G4）。

## 7. 每日进展（倒序）

### 2026-10-18
- 计划：审查 → 复现 → 修复 → 文档整理 → 浏览器端到端 → 对抗性复核。
- 完成：6 个审查 Agent + 2 个验证 Agent；启动 PostgreSQL 容器；前端依赖安装（pnpm 11.28.6）；前端 web-check 基线全绿（153 个测试 + build）；用户级通知 hook 装好（Stop / Notification → Windows toast + 提示音）；8 个并行工作包已启动。
- 之后完成：8 个并行工作包（A–H）全部交回并写入 §8；`dev check` / `web-check` / 完整 `dev test` 全部跑通；真 Chrome 浏览器端到端；独立对抗性复核发现 5 个漏洞，第二轮修复 R1–R5；浏览器验收的前端问题由 R6 修复；完整测试抓到 R5 的一个回归（P-R5b）并修好。
- 暂停（用户要求，2026-10-18）：不再启动新一轮对抗性修复。所有 Agent 已结束，临时库与进程已清理。
- 下一步（用户确认后）：①审阅并提交；②处理 §2 待决事项；③在真实浏览器里复验 R6 的视觉与交互；④对 R1–R6 做一轮复核；⑤清理可清理代码。

## 8. 问题解决记录

每个 P-条目对应[审查报告](../review/audits/2026-10-18-completeness-audit.md)里的同编号发现。所有修复都遵循“先写能失败的测试 → 看它红 → 再修 → 看它绿”；`红` 指修复前该测试的失败摘要，`绿` 指修复后的通过数。被改动的**既有**测试断言单独列出（含理由），供审阅。

### 工作包 A：Run 生命周期与 SSE

#### P-A1 [P1] 事件/终态落库失败后 Run 永远 running　状态：done
- 现象：`append_event` 或 `finish` 抛 `OperationalError`，库随后恢复；Run 仍 `running`，`GET /runs/{id}` 恒 503，同会话 submit 恒 409，cancel 返回“原执行进程已退出”，只有重启 API 才解锁。
- 假设与排除：✓ `_execute` 的 finally 只把 run_id 记入 `persistence_failures`，没有任何代码处理它（grep 只有 add 和 get 里的 503 判断）；✓ 事件落库失败时 consumer 异常经 `await consumer` 进入同一个 except；✗ “恢复逻辑不可复用”不成立，`initialize` 里“锁会话 + `runs.recover`”可直接提取。
- 根因：VERIFIED。
- 方案：**A 采用**——`persistence_failures` 改为 `dict[run_id, RunContext]`，提取 `_settle(db, context)`，`initialize` 和新的 `_recover_failed()` 共用；`_require_recovery()` 在 submit/get/cancel/events/progress 入口发现标记时只对这些 run 恢复一次，库仍不可用则 503 并保留标记，成功则清标记。**B 不采用**——后台定时重试任务：多一个任务和生命周期，用户请求触发就够。
- 实现：`backend/services/runs.py`。恢复事务用 `runs.recover` 同一行锁裁决，终态与终态事件同事务提交；不重放模型、不重复扣费、不丢已提交事件。
- 测试：`tests/integration/test_run_recovery.py`（append_event / finish 两种注入，库宕机时 503 且保留标记、库恢复后自愈为 `partial/unavailable`、第二次 submit 成功、模型仅调用两次、partial 事件恰好 1 个、cancel 幂等）。红 3 failed（`原执行进程已退出，需要恢复核对`）→ 绿 34 passed（含 test_runs / test_recovery / test_run_trace）。
- 改动的既有测试：`test_runs.py::test_persistence_failure_exposes_only_type_sqlstate_and_requires_recovery` 多 patch `runs.recover` 以模拟“库仍不可用”（在线恢复让原场景自愈）；原 503、sqlstate 断言保留。
- 遗留：恢复后终态文案沿用“原执行进程已退出…”，用户无法区分“落库失败”和“进程重启”。

#### P-A2 [P2] SSE 每连接轮询开销大　状态：done（**无红→绿实测**）
- 现象：0.25 秒一轮，每轮 `events()` + `get()`（`recorded_view` 含 4 个额外查询），约 8+ 条 SQL。
- 方案：**A 采用**——新增 `RunService.progress()` 只读 run 一行，返回（是否运行中, last_sequence），每轮约 3 条 SQL；空闲间隔 0.25→0.5→1.0 秒指数退避，有事件即复位；`: waiting` 心跳至多每 5 秒一次。**B 不采用**：LISTEN/NOTIFY，要新增机制。
- 测试：`tests/test_sse_polling.py`（FakeService 无 `get`、伪造 sleep 与 monotonic，断言退避序列 `[0.25, 0.5, 1.0, 1.0]`、心跳少于空轮询、游标不变）。**诚实说明**：修前未单独跑出红，红的依据是“旧代码调用 `service.get`，FakeService 没有该方法会抛 AttributeError”；“约 3 条”是代码推算，没用计数器实测。
- 遗留：未做 SQL 条数的量化对比。

#### P-A3 [P1/P2] 前端把 SSE 流结束当作 Run 结束，不重连　状态：done
- 现象：代理超时使流 EOF，UI `busy=false` 但 run 仍在跑，再发消息 409；点“停止”后 UI 立即解除忙碌。
- 假设与排除：✓ `connect` 在 `readEvents` 返回后直接取 `/runs` 并 `setBusy(false)`，不看 status；✓ Next 16 有 `experimental.proxyTimeout`（源码 `proxy-request.js` 默认 30000ms，官方 docs 目录无此项文档）；✗ “心跳是 45 秒超时的原因”不成立（SSE 一直有心跳，更可能是慢的普通 GET，REASONED）。
- 方案：**A 采用**——纯函数 `followRun({read, cursor, status, wait, active, limit})`：每次断开都查 `/runs` 状态；终态且游标 ≥ `last_sequence` 才结束，终态但有未读事件再读一次；未终态以当前最大 sequence 重连，退避 500ms 起上限 8s，连续无进展失败超 5 次返回 exhausted，游标有前进就重置预算；401/403/404 不重试。`cancel()` 不再包 `action()`，保持忙碌直到终态；Composer 新增 `stopping` 显示禁用的“正在停止…”。`next.config.ts` 设 `experimental.proxyTimeout: 120_000`。**B 不采用**：改用 EventSource（要整体重写 fetch 流水线且需带 Authorization 头）。
- 测试：`apps/web/tests/run-stream.test.ts` 8 个（流在终态前结束→带 `after` 重连；终态但有未读事件→再读；退避单调且 ≤8s；超限 exhausted；进展重置预算；401/404 不重试；取消后 cancelling→cancelled 才算终态；abort 立即停止；终态直接结束不重连）。红：模块不存在 → 绿 8 passed；web-check 全过（167 tests、build）。
- 遗留：重连等待期间只显示“处理中…”；`proxyTimeout` 对 standalone 运行时是否生效只验证了配置加载，**没在 Railway 实测**。

#### P-A4 [P2] ApiError 丢 code、409 不刷新、422 不可读、/models 静默降级　状态：done
- 方案：**A 采用**——`ApiError` 加可选 `code`，`apiError(status, body, fallback)` 被 `api()` 和 `readEvents` 共用；422 的 `detail` 只提取字段名（“输入不符合条件（expected_revision、text），请检查后重试”）；`refreshOnConflict` 对 saveConditions 的 409 与带 selection 的 send 的 409 重读 request 并提示；`loadModels()` 失败返回 offline 选项加明确文案“后端不可用，无法获取模型列表…”。**B 不采用**：所有 409 一律自动刷新（“此会话已有执行”的 409 与条件版本无关，刷新无益）。
- 测试：`api-error.test.ts`（code 保留、422 字段名可读且不含英文、非 JSON 502 回退）、`models.test.ts`；红：`code` 为 undefined、422 文案泛化、缺 `loadModels` 导出 → 绿。
- 遗留：409 刷新逻辑在 hook 里，无单测。

#### P-A5 [P2] 登录后创建会话失败留孤儿用户　状态：partial
- 方案：`loginUser` ref 缓存刚创建的用户，创建会话失败后再点登录复用该 token 重试；成功后清除，401 也清除。**B 不采用**：先持久化令牌到 localStorage（Identity 需要 session_id，会产生半成品身份的恢复问题）。
- 测试：无（逻辑在 React hook 内，无对应纯函数）。
- 遗留：仅同一页面生命周期内复用，刷新页面后孤儿用户仍会产生；后端没有清理接口（见待决 D2）。

### 工作包 B：酒店预订完整性

#### P-B1 [P1] 确认后崩溃订单不补发　状态：done
- 现象：用户已 confirm，进程在发 order 前崩溃；再 confirm/reconcile 只对账并落 `unknown`，hold 到期变 `failed`。
- 假设与排除：✓ `reconcile` 在 lookup 无订单且 `absence_final=False` 时一律写 `unknown/order_still_uncertain`，从不补发；✓ 供应商 order 在 `client_ref` + `FOR UPDATE` 下幂等，hold 有效时补发安全；✗ “对 unknown 也补发”不可行：order 超时或丢响应属于结果不明，必须保持只对账。
- 根因：VERIFIED（`reconcile` 没有“已确认、hold 有效、无订单”分支）。
- 方案：**A 采用**——`reconcile` 里当 `status == "confirmed"`、lookup 无订单、`absence_final` 为假、本地 `expires_at` 未到时调用现有 `_order`（同 `client_ref`）；其余路径不变，没有新增状态。**B 不采用**：unknown 也补发（违背“unknown 不得盲发”）。
- 测试：`test_booking_integrity.py::test_confirmed_crash_before_order_is_reissued_while_hold_is_valid`（红 `unknown == booked` → 绿，订单数 1，重复 confirm 幂等）、`test_confirmed_crash_with_expired_hold_fails_without_ordering`（order 调用 0 次）、`test_unknown_is_reconciled_by_lookup_and_never_blindly_reordered`。
- **改动的既有测试**：`test_recovery.py::test_confirm_process_kill_on_both_sides_of_supplier_commit_queries_before_retry[False]` 原断言“提交前被杀 → `unknown`，hold 过期后 `failed`”，**这正是被报告的缺陷本身**；改为两种崩溃时机都得到 `booked` 且订单数为 1。主任务审阅：接受。

#### P-B2 [P1] 同住宿段重复预订　状态：done
- 现象：同会话同一酒店再次搜索（新 offer/evidence）得到第二个 hold+order；同日期不同酒店也能同时 `booked`。
- 假设与排除：✓ `(session_id, evidence_id)` 唯一约束只防同一报价；✓ 入住区间在 `Booking.offer.request.start_date/end_date`，offer 里的 request 已经是该住宿段（`segment_request`），无需新增字段；✗ 无需新增列/约束，`owned_request` 已对 session 行加行锁，hold 事务内检查是串行的。
- 方案：**A 采用**——`reject_overlapping_stay`：同会话已有 held（未过期）/confirmed/unknown/booked 预订，同城市且 `[入住,退房)` 半开区间重叠时抛 409（`reason=duplicate_stay`，带可读 message）；新报价分支与“遗留 quoted 重试”分支都调用；同一报价重放走 `for_quote` 不受影响。**B 不采用**：数据库排除约束（属工作包 G 范围，应用层加会话行锁已够）。
- 调查结论：预订酒店与正式行程酒店是否一致——现状无任何校验；`selected_hotel_stays` 只是单次 run 内选择，设计写明“下一轮不强制旧选择”，设计文档也无“预订必须等于行程酒店”，所以**没加**。
- 测试：`test_overlapping_stay_is_rejected_for_same_or_different_hotel`（held/booked × 同店/异店，红 `DID NOT RAISE` → 绿；被拒报价在供应商侧无 hold）、`test_checkout_day_allows_next_stay_and_expired_hold_does_not_block`（11-03~05 与 11-05~07 可并存）。
- **更正（对抗性复核后）**：本条原先写“无需新增列/约束，`owned_request` 已对 session 行加行锁，hold 事务内检查是串行的”以及“遗留：未做真并发 hold 压力测试，靠会话行锁推理”——**这个推理是错的**。新报价先以 `quoted` 提交并释放会话锁，之后才在锁外调供应商 hold；并发的第二个请求此时只看到 `quoted`，检查放行，最终两个不同酒店、同日期的预订都变成 `held`（复核者复现 `assert 2 <= 1`）。已在 P-R1 修复。

#### P-B3 [P2] 其它预订问题　状态：partial（c 为待决）
- (a) `transition()` 同状态丢弃新 `error_code`：状态不变但字段有变时返回合并后的新对象且不追加 history（`test_same_status_transition_keeps_new_error_code_without_new_history`）。
- (b) `quoted` 永不过期：`Booking.quote_lapsed(observed_at)`，`business_context` 的 active 过滤加一行（`test_business_context_omits_quote_past_its_validity`，临时去掉该行验证过红）；只过滤上下文，不把库里的 quoted 改成 expired。
- (c) 供应商 429/非 409 的 4xx 把报价标 `failed`：**未改**，`test_eval_state.py:303` 注明是有意的业务终态；若改成 429 不烧报价，利是可直接重试，弊是要改评测口径。列入待决 D4。
- (d) HTTP 与工具路径对 live/synthetic 报价状态码不一致：统一为 `403 blocked`（策略性拒绝）；**改动的既有测试** `test_hotel_links.py:107`、`test_synthetic_data.py:86` 的 `422` 改 `403`。
- (e) 预订按 JSON 时间戳**字符串**排序：根因 VERIFIED（微秒为 0 时序列化为 `...:00Z`，字符串降序会排在 `...:00.5Z` 之前，解释了偶发的 `rows[0]==held` 失败）；`order_by` 改为 `cast(payload["history"][0]["at"].astext, DateTime(timezone=True)).desc(), id`；`test_session_order_uses_real_time_not_timestamp_text` 确定性构造 12:00:00 与 12:00:00.5。
- (f) 前端币种符号写死 `¥`：`moneyLabel(amount, currency)` 用 `Intl.NumberFormat`，JPY 显示 `JP¥45,000`（有意变化）；币种代码非法时回退；`availability.test.ts` 10/10。

#### P-B4 [P2] 并发确认的中间状态　状态：done
- 现象：见审计报告 §5 的更正。0.4 秒延迟的 `supplier.order` + 3 个并发 `confirm`，修复前 `['booked','unknown','unknown']`。
- 修复后三个都 `booked`、订单数 1。测试 `test_concurrent_confirm_never_exposes_unknown_while_order_is_in_flight`。

### 工作包 C：条件校验、偏好与记忆

#### P-C1 [P1] PATCH /preferences 把已确认的对话事实重写成 manual　状态：done
- 假设与排除：✓ `change()` 把同字段所有 active 事实标 superseded 再全部新建 manual（复现：id/来源/原话全变）；✗ “前端只提交变化项”不成立（每次提交整个数组）；✓ 手动上限 200 字、对话事实上限 80 字，不一致。
- 方案：**A 采用**——服务层按值 diff：值不变的 active 行保持原行（只更新 ordinal），被移除的值标 superseded，新值才新建 manual；重复值在领域层 `PreferencePatch` 校验返回 422（与 `memory.py:358` 同口径；不放在 `PreferenceValues`，否则库里历史重复值会让读取失败）；手动值上限统一为 80 字（`MANUAL_VALUE_LIMIT`），只对新增值校验，历史更长的值不改动时仍可保存。**B 不采用**：前端只发 diff（服务端仍须自洽）。
- 测试：`test_preferences.py::test_patch_diffs_by_value_and_keeps_confirmed_dialogue_facts` 等 3 个；红：保留行 id 不等、重复值 `DID NOT RAISE` → 绿 13 passed；边界：值相同 revision 不增、仅换顺序保留原行且 revision+1、150 字历史值保留、81 字新值 422。

#### P-C2 [P2] 文本含 NUL 返回 503　状态：done
- 假设与排除：✓ PG 的 text 和 JSONB 都不能存 NUL；✓ `transaction()` 把所有 `SQLAlchemyError` 映射 503；✗ 日志泄露正文（`database_error_details` 只记类型与 sqlstate，新测试断言日志不含正文）。
- 方案：**A 采用**——领域层新增 `reject_nul`（`Text`、`Place` 类型带它），覆盖 city、hotel_search_location、segments.city、interests、硬/软条件、选择卡 `Answers`、`PreferenceValues`；`transaction()` 对 `DataError` 返回 422，`IntegrityError` 仍 503（服务端逻辑或竞态，不是输入问题）。**B 不采用**：只靠 DataError 映射（psycopg 客户端侧 NUL 没有 sqlstate，不能代替领域校验）。
- 测试：`test_travel_request.py::test_text_fields_reject_nul_before_reaching_database`、`test_service_common.py`（新增）、`test_input_limits.py::test_nul_in_preferences_and_request_is_422` 与 `test_nul_in_message_is_422_not_503`；红：`DID NOT RAISE`、`(503,'unavailable') == (422,'validation')` → 绿。
- 遗留：`MessageInput.text`、`DemoLogin.display_name` 在领域层未加 `NoNul`，靠 DataError→422 兜底。

#### P-C3 [P2] 日期/规模无上限　状态：done（**日期下限由主任务调整**）
- 现象：接受 1900–9999、120 晚、2 成人 5 间房，下游逐日展开约 295 万项。
- 方案：**A 采用**——`check_limits(updated, changed, today)` 是单一入口（HTTP 与工具都经 `apply_request_patch`）：最长 30 晚（含）；日期窗口上限今天+3 年；房间数 ≤ 成人+儿童人数；只在相关字段变化时校验，历史越界行仍可编辑其他字段；时钟可注入（`TravelService(today=…)`）。**B 不采用**：放进 pydantic 模型验证器（窗口随时间移动，会让历史行读取失败）。
- **主任务调整（已被 2026-10-19 决定取代，下限改为“今天”）**：C 原实现的下限是“今天-1 年”滑动窗口，而现有测试/夹具用固定的 2026 年日期，走默认时钟的集成测试会在 2027-10-18 后无故变红（时间炸弹），且和待决 D3（允许过去日期）推荐相冲。改为**固定下限 2000-01-01**（`EARLIEST_DATE`），上限仍是今天+3 年。
- 测试：`test_travel_request.py`（`test_trip_dates_and_length_are_bounded` 等；恰 30 晚通过、31 晚拒绝；窗口端点通过、端点外拒绝）、`test_input_limits.py::test_out_of_range_request_is_readable_422`（HTTP 层 4 种越界都是 422 且 revision 不变）；红 14 failed（`apply_request_patch()` 无 `today` 参数）→ 绿 64 + 73 passed。
- 需用户确认：30 晚、未来 3 年、房间数上限这三个默认值（待决表）。

#### P-C4 [P2] GET 有写副作用且锁会话　状态：done
- 方案：**A 采用**——新增只读 `read_request`（不锁，缺行时返回未入库的空行），`get_request_view` 改用它；`owned_card` 加 `lock: bool = True`，写路径不变，只有 `ChoiceService.get` 传 `lock=False`。**B 不采用**：把 `TravelService.get_request()` 也改成无锁（工具路径依赖其序列化，有行为风险）。
- 测试：`test_input_limits.py` 三个——另一个连接持有会话行锁时 GET 必须 5 秒内 200 且行数仍为 0，写入必须阻塞；红：读接口被锁住超时 503（`OperationalError sqlstate=57014`）→ 绿 9 passed。

#### P-C5 [P2] 前端偏好面板等　状态：partial（e 未做）
- (a) 有未保存编辑时后台刷新只更新事实列表和画像，不覆盖表单与 revision（之后保存得到 409 而非静默覆盖）；`<details>` 折叠时不请求；(b) 分出 current / elsewhere（其他旅行的临时偏好，单独折叠）/ history，其他会话的 trip 事实显示“仅用于其他旅行”；(c) “清除偏好”改页内 Popover 二次确认（项目已有 shadcn/radix）；(d) 攻略页城市/来源读 `article.city` / `source.provider`，时间统一 `formatTokyo`（固定 Asia/Tokyo）；(f) 新增 `preference-form.test.ts`、`format-time.test.ts`，171/171 通过。
- (e) `/models` 显示今日预算用尽：**未做**——需要改 `providers/claude_agent/budget.py`（控制花费的核心代码，不在 C 范围）；建议由负责 budget 的工作抽出 `daily_spent/daily_exhausted` 共享函数再让 `model_options` 调用。
- 遗留：Popover 无组件交互测试；`bookings.tsx` 内联的东京时区格式化可改用 `formatTokyo`。

#### P-C6 [P2/P3] 画像并发、catalog 残留、source_turn_id　状态：done / 部分评估
- 画像：按 `(user_id, revision)` 进程内 single-flight（`asyncio.shield`），同 revision 已有有效画像直接复用；“引用必须属于 active 事实”校验原样保留；测试 `test_same_revision_generation_is_single_flight_and_reuses_valid_result`（红 `3 == 1` → 绿）。局限：多进程下仍靠 revision CAS；副作用：事实没变时点“更新画像”不会重新生成。
- catalog：`import_catalog(..., prune=False)`，`--prune` 把传入条目当完整快照并删除其余条目（空快照加 prune 抛 ValueError；补充快照不能用）；改了 `data/import_catalog.py`。
- `source_turn_id`：只评估——工具路径写真实 run id，HTTP 路径写随机值，该列无读取方；见 P-G5。

### 工作包 D：行程规划与日历

#### P-D1 [P1/P2] 草稿过期后相同参数重新暂存报 409　状态：done
- 假设与排除：✓ 幂等键只取决于 `StageInput`，不含时间，命中过期缓存是必然的；✓ 证据过期时原有 `resolve_records` 已抛 `evidence_stale:<kind>` 并提示重新查询；✗ 没有新增 `evidence_expired`，复用现成 code。
- 方案：**A 采用**——缓存已过期就当作没有缓存，走正常生成，旧草稿保持 expired，新草稿经新增的 `operations.replace` 覆盖同一幂等键；未过期回放逻辑原样保留；会话锁已串行化并发。**B 不采用**：只改报错文案（模型复用旧参数仍卡死）。
- 测试：`test_plan_lifecycle.py` 4 个（同参数过期后新草稿且回放幂等、过期 patch、并发只生成 1 个新草稿、证据也过期则提示重新查询且不变更）；红整个文件 15 failed → 绿 17 passed。

#### P-D2 [P1 测试空洞] 锁定接口版本校验与 HTTP 路由无覆盖　状态：done
- 根因：VERIFIED（变异 M13 存活；原测试用随机 uuid 当 item_id、裸 `pytest.raises(ServiceError)`）。
- 实现：服务层断言 409 `plan_version_changed` 且计划内容不变；`PATCH /plans/{id}/locks` 的 HTTP 测试覆盖 200、no-op 不升版、409、422、401、404；ics HTTP 测试逐事件校验 DTSTART/DTEND（保存值转 UTC）、UID `{item_id}@travel-agent` 跨版本稳定、SEQUENCE、DTSTAMP、SUMMARY 的 `, ; \ 换行` 转义、每物理行 ≤75 字节、折行还原一致、重复下载逐字节相同、`trip-v1.ics` 文件名头、`text/calendar; charset=utf-8`、`no-store`。为在 HTTP 里断言具体 code，错误体新增可选 `reason`（只在设置时输出，固定英文标签，不影响对 503 整体相等的既有断言）。
- `tests/integration/test_plans.py` 新增 `assert_error(failed, status, code, reason)`，约 12 处裸 `pytest.raises` 改为断言状态/类别/reason（过期、条件变化、证据过期、硬冲突、他人草稿按 `EXPECTED` 表逐项断言，不能互相顶替）。
- 变异验证：去掉版本判断后 `test_lock_rejects_a_stale_expected_version_without_changing_the_plan` 与 `test_locks_http_contract` 失败，M13 被杀死，已还原。
- 全仓裸 `pytest.raises(ServiceError)` 共 61 处，除 `test_plans.py` 外尚未改（清单：test_memory 10、test_travel 6、test_choices 4、test_planning 4、test_hotels/test_lodging_budget/test_tool_failure_detail 各 3 等）——**后续项**。

#### P-D3 [P2 测试空洞] 修复算子的锁定项守卫　状态：done
- 假设与排除：✓ `settle` 在 drops/moves 之后会重建紧随其后锁定项的 `route_evidence_id` 且未披露；✓ 实测只改路线引用不改时间/内容；✗ 没发现锁定项时间或内容被修改。
- 实现：`repair()` 末尾比较输入与输出里锁定项的路线引用，不同则追加披露“锁定项…时间与内容未动，仅更新了路线引用”。
- 测试：`test_repair.py` 新增 `test_a_locked_item_is_never_moved_or_resized_and_the_conflict_stays_reported`（平移/换天/夹时长 3 个）、`test_unlocking_the_same_item_lets_the_repair_move_it`（对照）、两个路线引用用例、`test_repair_also_fixes_an_old_conflict_the_patch_did_not_touch_and_discloses_it`；红：缺少披露 → 绿 19 passed；去掉 `shifts` 的 `locked` 守卫后 `...[shift]` 失败，M9 被杀死，已还原。
- 取舍：修不动锁定项时冲突留在校验报告里（原测试要求 `disclosed == ()`）；旧冲突项保持由 repair 修复并披露，**不限制范围**——限制需把 touched id 贯穿 stage→repair，且可能让草稿因旧冲突而无法确认。待决。

#### P-D4 [P2] 加锁使待确认草稿失效　状态：done（选明确报错，未做合并）
- 评估：锁定标志是版本内容的一部分，也是 `expected_version` 乐观并发的依据，版本不可变，所以保留“加锁创建新版本”；相同锁请求不升版（已有测试固定）。
- 方案：**A 采用**——统一 `reason=plan_version_changed`，提示改为“正式版本已变化（例如刚修改了锁定），请重新生成patch”，stage/confirm/get_draft/locks 都带上。**B 不采用**：“仅锁变化时合并草稿”（需三向合并、冲突项拒绝，还要改前端 `planUnavailable`，成本高于收益）。
- 测试：`test_locking_invalidates_a_pending_draft_with_a_clear_reason_but_a_noop_lock_does_not`。

#### P-D5 [P2] 工具与错误细分　状态：done
- (a) `get_saved_plan` 的 `items_only` 每项带 `locked`；patch 错误拆成 `patch_item_locked`（新增 `PatchItemLocked`）与 `patch_invalid`；(b) 新增全局 `RequestValidationError` 处理器，422 返回 `{code:"validation", message}`（字段名取 loc 最后一个字符串；顶层错误用泛化消息不回显输入值），OpenAPI 仍列默认 422 schema 所以 api-types 不变；确认过期草稿的 409 带 `draft_expired`；(c) 首次暂存的 `PlanRow` 改为首个草稿真正落库时才创建；(d) `differences()` 用 `SequenceMatcher` 检测相对顺序变化（以 `op="update"`、before==after 出现，单纯插入不误报）。
- 测试：`test_items_only_read_exposes_locked_and_patch_errors_tell_missing_from_locked`、`test_a_failed_first_pass_leaves_no_empty_plan_row`、`test_request_validation_errors_use_the_service_error_shape`（4 个参数化）、`test_plans.py::test_pure_reordering_shows_up_in_the_diff_but_identical_order_does_not`；红：`PatchItemLocked` 属性不存在、校验格式四例返回 `{'detail':[...]}` → 绿 22 + 17 passed。
- 遗留：`ToolReason`/`StageReason` 是 `domain/execution.py` 的封闭枚举，`patch_item_locked` 与 `plan_version_changed` 在运行结果里目前归为 `other`，前端“已锁定”文案不再精确（要改枚举、重新生成 api-types、改 `business-status.ts` 与 `error-explanation.ts`）。

#### P-D6 [P2] 单城市请求不检查停留时长　状态：not-done（只记录，待决 D7）
- 设计无明文；多城市计划（`2026-10-10-multi-city-pacing.md`）把停留时长列在多城市范围；若要改只需去掉 `validator.py:272` 的 `request.segments and`，但“未修复冲突会阻止确认”，对既有单城市行程有影响，需评估。

#### P-D7 [P2] ics 与前端下载　状态：done（酒店事件默认不做）
- 后端：每个事件加 `SEQUENCE:{plan_version}`；DTSTAMP 取 `saved_at`；证据过期（`needs_refresh` 非空）时每个事件 DESCRIPTION 追加“提示：部分来源或报价已过期，出行前请重新确认”。前端：`icsFilename` 从 Content-Disposition 取名，退回 `trip.ics`；下载为 `trip-v{n}.ics`；`revokeObjectURL` 延后 60 秒。
- 测试：见 P-D2 的 ics 测试；`calendar-file.test.ts` 2 个（**文件和测试同时写，没有单独录先红输出**）。
- 备注：D 用 Python 重写几个文件时行尾从 CRLF 变成 LF，由 `.gitattributes` 规范化。

### 工作包 E：Agent 工具层安全

> E 因额度限制中途终止过一次，恢复后从保存的进度继续。红→绿方式如实说明：E3 的围栏与限流测试是**先实现、再临时还原那两处改动看到红**；E2 的红是临时换回 git HEAD 版 `fencing.py` 看到的；E5 的 `tests/test_mcp_exposure.py`（暴露集合与 kind 一致性）是先实现后补的，**没有单独红过**。

#### P-E1 [P1] explicit_fields 自填绕过手填保护　状态：done
- 现象：用户手填 city=京都，模型带 `explicit_fields=["city"]` 就能改成大阪，服务端不核对新值是否出自用户原话（攻略/供应商文本可诱导模型改城市、日期、人数；预算放宽有专门拦截，其他字段没有）。
- 假设与排除：✓ `RunContext` 里拿不到用户原话，但 `runs.owned(...).user_text` 就是 `propose_memory` 用的同一来源，复用它；✓ 预算放宽拦截（`hotel_budget_requires_selection`）在服务层，不受影响；✓ 核对失败不报错，仍返回 ok，字段落入 `skipped_fields` 并在 `warnings` 里说明。
- 根因：VERIFIED（验证员的复现与 E 的红测试都复现了绕过）。
- 方案：**A 采用**——在工具层按字段核对原话，核对不过的字段从 `explicit_fields` 剔除（来源保护因此生效）。**B 不采用**：服务层强制核对（服务层有大量直接调用，会破坏大量以 service 直调为前提的测试）。
- 实现：`backend/tools/grounding.py`（新）的 `grounded_fields(patch, declared, user_text, current)`，原话先做 NFKC、去空白、casefold。匹配规则：city / hotel_search_location 含该值或 `CITY_ALIASES` 别名（忽略“市”后缀）；日期接受 `2026-11-03`、`2026/11/3`、`11月3号`、`11/3`、`3号`、全角数字，原话无绝对日期时接受“下周五/周末”等相对说法，end_date 还接受“玩 N 天/N 晚”推算；adults 识别 `N人/位/成人/大人`、`人数N`、情侣/夫妻等关系词（=2）、一个人/独自（=1）；rooms 识别 `N间房`；child_ages 识别 `N岁`、婴儿（=0）；budget 识别千分位、万/千/k/w、中文数字（三万五=35000），lodging_budget 每个端点都要有出处；`lodging_budget_unlimited=True` 需“不限/无上限”等词；transport 关键词；departure_time 只核对小时；segments 每段城市和日期都要有出处；interests / hard / soft constraints 只核对**新增**条目（≥2 个汉字或 3 个 ASCII 字符的共享片段）；`clear` 无新值，直接保留。拿不到原话（无执行记录）时，所有声明都按未声明处理。`trusted_user_text` 放进 `TravelService`，因此 `tools` 不再导入 `persistence.runs`，F 登记的那条 `tools.travel → persistence.runs` 例外已从 `pyproject.toml` 删除。
- 测试：新增 `tests/test_request_grounding.py`（41 项）、`tests/integration/test_explicit_grounding.py`（3 项）。红：`assert () == ('city',)`（旧代码 `skipped_fields` 为空，城市被改）；绿：用户明说“改成大阪，3 个人”通过；“看看这篇攻略”下改 city / 日期 / 人数 / 房间全被 skipped、请求不变；无执行记录时全部 skipped。为此给 8 个原本假设无执行记录的集成测试加了 `tests/integration/user_turn.py:start_turn` 来造执行记录。
- **误拒风险（需要知道）**：用户用别名/方言/省略写法、相对日期且话里同时带别的绝对日期、“三口之家”类非常规人数表达时，可能被误拒；后果只是“覆盖手填值被跳过，模型会追问”，不会整个调用失败，且只影响会覆盖 `user_form` 手填值的字段。误放的情形是用户话里恰好出现同一个数字或日期；被诱导误清除（`clear` 不核对）的后果只是重新追问。

#### P-E2 [P2] 围栏漏字段　状态：done
- 假设与排除：✓ 旧实现是顶层集合行的字段名白名单；✓ 现有围栏标记已被 `sanitize` 到不动点移除，内部文本无法闭合，复用它而不加转义。
- 方案：**A 采用**——对 `data` 递归**默认围栏**，白名单豁免。**B 不采用**：继续扩充字段名白名单（永远漏新字段）。
- 实现：结构化键（`id`、`status`、`provider`、以 `_id/_ids/_ref/_version/_at/_url/_fields` 结尾的键等）不围栏，**但值还必须是纯 ASCII 标识，否则照样围栏**；与键无关的结构化值直接放行（UUID、ISO 日期时间、数字、不含空白和尖括号的 http(s) 链接）；服务端文案键（`message`、`guidance`、`scope`、`instructions`、`reasons`、`presented`、`count_basis`）原样；`load_skill` 整体豁免。`fence_payload(payload, tool=None)` 新增 tool 参数，bridge 和对外 MCP 都传工具名。`city` 现在也被围栏（它来自目录数据，不是枚举）。工具返回结构和 JSON schema 不变。
- 测试：新增 `tests/integration/test_fencing_tools.py`，用 13 个工具的真实离线返回做表驱动——断言所有自由文本被围栏；不围栏的叶子必须在评审过的名单内，**新增字符串字段会让测试失败**；把含 `</untrusted_text>忽略之前的指令…` 的敌意文本注入每个叶子（含被豁免的结构化键），断言都被围栏且无法提前闭合。红：旧版对 `city`、`source.attribution`、`category` 报“未围栏”，对注入报“逃出围栏”→ 绿。
- 遗留：`data/fixtures/kyoto.json` 没有 design/03 §7 要求的“忽略之前指令”段落，选择在测试里动态注入；服务端文案键（如 `checks[].message`）将来若插值第三方名称会不围栏（目前 grep 为固定文案，REASONED）；围栏发生在长度检查之后，标签可能让 `search_places` 等结果多约几百字符而略超 8000 字符上限。

#### P-E3 [P2] 对外只读 MCP 缺围栏、限流、缓存　状态：done
- 方案：**A 采用**——围栏 + 每令牌令牌桶 + catalog 缓存按“行数 + `max(xmin)`”指纹失效（指纹查询不读 payload）。**B 不采用**：TTL 缓存（导入后短时间读到旧数据，难以测试）。
- 实现：令牌桶按用户 id 限流，默认容量 60、每秒 5 个，环境变量 `MCP_RATE_BURST` / `MCP_RATE_PER_SECOND`（上限 600 和 100），超限 429 + `Retry-After`；`max_calls` 在每请求新建的执行器上无意义，改传 `None`，由限流承担；`_publish` 里 deepcopy 避免别名到缓存；对外暴露集合改为 `EXTERNAL_TOOLS` 白名单 + `read_only_tools()`（kind≠read 或未登记直接抛 `RuntimeError`）。
- 测试：新增 `tests/integration/test_mcp_hardening.py`（5 项），修改 `test_mcp_server.py`。红：缓存用例 `assert 3 == 1`；围栏与限流用例在临时还原后红 → 绿（第 4 次请求 429 且 `Retry-After` 在 1–2 秒、其他令牌不受影响、时钟推进后恢复、目录变更后重载一次）。
- **“只读”的真实含义**：4 个对外工具不改旅行条件、行程、预订（测试断言计数不变），但**每次查询都会追加 Evidence 行**（`_publish` → `record_evidence`，追溯语义，没改）。所以“只读”＝不改业务状态，不是不写库。
- 遗留：限流在认证之后，未认证洪水仍各打一次认证查询；计数与缓存都是进程内的，多实例各自独立、重启清零。

#### P-E4 [P2] worker 环境带供应商密钥　状态：done（部分保留，REASONED）
- 假设与排除：✓ 工具在 worker 内执行（`worker.py` 构造 `DatabaseTools`，`real_data` 时 `LiveData.from_environment(os.environ)` 在 worker 进程里读这些 key），所以实时 worker 确实需要 key；✓ 离线 worker 不需要。
- 方案：**A 采用**——`environment.py` 新增 `live: bool = False`，`live.py` 传 `live=real_data`，四个 `LIVE_SECRETS`（`GOOGLE_MAPS_API_KEY`、`RAKUTEN_APP_ID`、`RAKUTEN_ACCESS_KEY`、`RAKUTEN_AFFILIATE_ID`）仅在 live 时进白名单。**B 不采用**：完全移除（实时数据工具会失效）。
- 测试：新增 `tests/test_worker_environment.py`（8 项）；红：离线环境里仍有这些 key、不认 `live` 参数 → 绿（离线 worker 不含任何供应商 key、token 或数据库 URL；live worker 只多这四个数据 key，不含 DeepSeek、Anthropic、数据库 URL）。两个 monkeypatch `worker_environment` 的集成测试改为接受 `live` 参数。
- 遗留（REASONED）：实时 worker 里的 claude CLI 子进程仍继承这四个 key；彻底隔离需要把工具执行挪出 worker，是架构改动，没做。

#### P-E5 [P2] 写操作已提交却报失败；运行时 assert；kind 与暴露集合　状态：done
- 假设与排除：✓ 重试会重复写入（草稿、预订、记忆卡片）；✓ `kind` 默认 `read`，不能单独派生出暴露集合（`search_hotel_offers` 等 read 工具也会写 Evidence，但不应对外）。
- 方案：**A 采用**——返回最小确认。**B 不采用**：事务回滚（写操作已提交，展示层无法回滚）。
- 实现：`contracts.committed_confirmation` 只保留标识、版本和 `status/changed_fields/skipped_fields`，附“已提交…不要重复调用”提示（失败结果不伪装成成功）；`WRITE_KINDS = {state, draft, side_effect}`；`travel.py` 在超长检查里对写类成功结果返回最小确认，读类与 presentation 保持 `blocked`；bridge 用 `Recorder` 记录执行器已返回的结果，之后 emit/序列化失败时，写类工具回最小确认，读类或执行器没运行则仍 `unavailable`；`_execute`、选择卡分支、`EntityInput`、酒店展示共 5 处 `assert` 改为显式 `ServiceError` 校验。
- 测试：新增 `test_write_result_too_long.py`（3 项）、`test_mcp_exposure.py`（3 项，含全部 18 个工具的 kind 快照，**新增工具必须先登记**）、`test_mcp_bridge.py` 加 3 项（接收器失败、序列化失败、工具未运行）。红：`assert ('blocked' is None)`、`assert (True is False)`、`assert not [<ast.Assert>]` → 绿（写入真实发生 rooms=2，结果 `code=None`，数据只含标识）。
- 遗留：plan 区域的 `assert parsed.draft_id is not None`（D 负责）与 `compact_plan_items` 里的 `assert isinstance(cards, list)` 没动，只涉及类型收窄。

#### P-E6 [P2] /demo/login 无速率限制　状态：done
- 假设与排除：✓ 持久化限流需要新表，G 独占 models/migrations，所以采用进程内实现；✓ 返回 429 + `Retry-After` 不改变 OpenAPI 契约（`RateLimited(ServiceError)` 子类，只在已有异常处理器里加 header，`test_web_schema` 仍绿）。
- 方案：**A 采用**——按客户端 IP + 全局两道滑动窗口，默认每 IP 30 次、全局 300 次、窗口 600 秒，本地演示不受影响。**B 不采用**：只做全局上限（单个 IP 就能耗尽全部额度）。
- 实现：环境变量 `DEMO_LOGIN_PER_IP`、`DEMO_LOGIN_GLOBAL`、`DEMO_LOGIN_WINDOW_SECONDS`（上限 1000 / 5000 / 86400，非法值启动即 `ValueError`），三个键加进 `CONFIG_KEYS` 所以 `.env` 也能配；时钟可注入；未启用演示登录的 403 不计数；被拒绝的请求不计入窗口。
- 测试：`tests/test_rate_limit.py`（5 项）、`tests/integration/test_demo_login_limit.py`（3 项）；红：`SessionService` 不认 `login_per_ip` → 绿（同 IP 第 3 次 429 且带 `Retry-After`、换 IP 不受影响、全局满了新 IP 也 429、窗口过后恢复）。
- 局限：进程内计数，多实例各自计算、重启清零；反向代理后 `request.client.host` 是代理地址，需 uvicorn `--proxy-headers`，否则每 IP 限流退化为全局限流。
- 令牌有效期：代码默认 30 天（`DEMO_TOKEN_DAYS` 可配 1–365），ADR-006、`backend/api/README.md:4`、`README.md:128` 写的是 24 小时——**文档与代码不一致**，处理建议见待决 D8。

#### P-E7 [P2，需用户决定，未实现] 实时调用无按用户的额度
- 现状：live 调用的预算与独占锁是全局的（`runs.py:178`；`budget.py` / `live.py` / `ledger.py`）；一个用户用光全局日预算会影响所有人，一个用户占住全局锁会让其他人排队。
- 已核实：`budget.py:71` 的 `UNCAPPED_CNY_DAY="2026-10-04"` 只在 `budget.py` 内被引用，今天是 2026-10-18，该日期已过，是遗留死代码；建议删除，但属于费用逻辑，只报告不改。
- 方案（见待决 D1）：1. 每用户每日 live 次数/金额配额，存新表（成本最高、最准，需要 G 的迁移）；2. 进程内每用户令牌桶 + 每用户并发 1（成本低，多实例各自计算、重启清零）；3. 只给 live 加白名单或邀请码（成本最低，但等于关闭公开访问）。

#### E 动到的非本包文件
- `tests/test_architecture.py`：D 报告的失败原因是 F 加的 `ignore_imports` 在该测试的空模块导入图里全部“无匹配”，与围栏无关；E 在临时配置里把 `ignore_imports` 清空后转绿。
- `pyproject.toml`：删除 `tools.travel -> persistence.runs` 一行（见 P-E1）。
- `tests/integration/test_run_trace.py`：只改 monkeypatch 的函数签名。
- 主任务补修：`tests/test_fencing.py`、`tests/integration/test_demo_login_limit.py`、`tests/integration/test_explicit_grounding.py`、`tests/integration/test_plans.py` 里 15 个 mypy strict 类型错误（`dev check` 因此变红）；`httpx` 误用为 `httpx2`，`ToolResult.data` 为 `object` 需收窄，`example.segments` 可为 None。

### 工作包 F：平台、测试基础设施、健康检查、分层

#### P-F1 [P2] Windows Proactor 事件循环与 psycopg 不兼容　状态：done
- 假设与排除：✓ 根因是默认循环（仓库其余 30 多处入口早已用 `asyncio.Runner(loop_factory=asyncio.SelectorEventLoop)`）；✗ `worker.py` 的 `asyncio.run` 是有意保留 Proactor（SDK 子进程），不改；`backend/cli.py` 的 `asyncio.run(offline(...))` 未核查是否连库，没改。
- 方案：**A 采用**——沿用全仓现有写法，不新增工具函数，没有第二份实现。**B 不采用**：新建共享 helper（`eval/` 里已有 `selector_runner`，scripts 导入会反向依赖 eval）。
- 实现：3 个测试（`test_eval_v2`、`test_synthetic_data`、`test_three_city_fixture`）与 2 个脚本（`export_history.py`、`probe_hotel_sort.py`）改用 Selector 循环，断言未动。
- 测试：新增 `tests/test_event_loop_entrypoints.py`，AST 扫描 `scripts/*.py` 与 `tests/integration/*.py`，裸 `asyncio.run` 或不带 `loop_factory` 的 `asyncio.Runner()` 报错。红：列出 5 处 offenders → 绿 13 passed；原 4 个基线失败转绿。

#### P-F2 [P2] pytest 默认 basetemp 在本机 PermissionError　状态：done
- 方案：**A 采用**——`tests/conftest.py` 的 `pytest_configure` 在 `PYTEST_DEBUG_TEMPROOT` 未设置时指向 `.cache/pytest-tmp`（已设置时不覆盖，`dev.py`/CI 自己设置）；pytest 自带 `pytest-N` 编号，并发互不覆盖。**B 不采用**：在 pyproject 写 `--basetemp`（并发运行会互相清空，且覆盖显式传参）。
- 测试：`tests/test_tmp_root.py::test_bare_pytest_uses_project_cache`（子进程裸跑）；红：PermissionError → 绿；不带 `--basetemp` 直接跑 `test_profile.py` 通过。

#### P-F3 [P1/P2] /health 未校验迁移　状态：done
- 方案：**A 采用**——新增 `GET /health/ready`：alembic `ScriptDirectory` 读 head（`@cache`），查询 `alembic_version`，表不存在或版本不等于 head 返回 503；`/health` 保持轻量 liveness（`test_database_outage` 要求库不可达时它返回 503）；`docker-compose.demo.yml` 的 api 健康检查改用 readiness；`web-generate` 后契约只多了 `/health/ready`。**B 不采用**：改 `/health` 本身（破坏 liveness 语义和现有测试）。
- 测试：`test_health_ready.py` 3 条（空库 `/health` 200 与 `/health/ready` 503、迁移后 200；落后于 head 503；已迁移 200），红：路由不存在 → 绿 9 passed（含 test_sessions）。

#### P-F4 [P1] 分层契约过窄　状态：done（债务已登记）
- 做法：用 grimp 按包对统计直接导入边，逐条核对后再写契约。新增 8 条 `forbidden` 契约（`allow_indirect_imports=true`，只管直接导入）：persistence 不依赖上层；只有入口导入 api；生产代码不导入 eval/data/mock_supplier；adapters 不依赖 services 等（登记 1 条）；tools 不依赖 providers/mcp/persistence/api（登记 1 条）；services 不导入 tools（登记 2 条）；services 不导入 providers 实现（登记 6 条）；providers 与 agent 不导入 services（登记 4 条）。结果 `11 kept, 0 broken`。**B 不采用**：移动 fixture 模块或改注入（`hotels.py`/`planning.py`/`runs.py` 是并行工作包在改的文件，易冲突）。
- 验证契约能抓新违规：临时放 3 个探针模块，`lint-imports` 报 `8 kept, 3 broken`，删除后恢复全绿。契约刚建好就抓到并行工作包新增的 `backend/tools/travel.py:40 from backend.persistence import runs`。
- **分层债务清单**（边 → 原因 → 建议消除方式）：见 [分层债务](../execution/layering-debt.md)。`ARCHITECTURE.md` 那句“分层受 import-linter 保护”已改为“受 11 条契约保护，债务逐条登记”。

#### P-F5 [P2] CLI 版本白名单诊断　状态：partial（白名单未放宽，4 个用例仍 blocked，待决 D5）
- 假设与排除：✓ 白名单只用于 `disable_auto_compaction`（`no_compaction` 与 `baseline_b2` 评测变体），判断条件是 (SDK, CLI) 组合是否在已离线实测列表；✓ 带工具的 `get_context_usage` 探针会触发计数 API 和费用，所以未知版本不做运行时探测；✓ CI 固定 2.1.295；✗ 未读 ADR 003/004/028 全文，依据来自代码注释与 CI。
- 方案：**A 采用**——白名单提成 `VERIFIED_COMPACTION_CONTROL`，拦截时 `RuntimeOutcome.text` 写明当前 SDK/CLI 版本、已验证列表、安装命令与 `scripts/dev.py doctor`（`code` 与 `reason` 不变）；新增 `uv run python scripts/dev.py doctor`，只读检查 Python 3.12、uv、Node 24+、pnpm 11、claude CLI 是否在白名单、PG（TCP 5434）、pytest 临时目录是否可写，失败项给修复提示，有失败退出码 1。**B 不采用**：放宽白名单（安全边界）；xfail 或跳过那 4 个用例（明令禁止）。
- 测试：`test_cli_version_guard.py`（红：导入 `VERIFIED_COMPACTION_CONTROL` 失败 → 绿，52 passed 含 test_claude_runtime）、`test_doctor.py`（5 组）。本机实跑 `doctor`：除 claude CLI 2.1.302 外全 ok。
- 是否把 2.1.302 加入白名单：建议暂不加。若要加，先做：装 2.1.302 后用 `disable_auto_compaction` 配置跑离线 SDK 脚本探针确认不触发计数 API 费用；确认无 `compact_boundary`、无 `get_context_usage`，`literal_prompt_supported` 比较不受影响；跑 `test_claude_runtime` 与 `test_evaluation_variants` 的实 CLI 用例；`check.yml` 固定版本同步为 2.1.302 并更新 ADR。或降级：`npm install --global @anthropic-ai/claude-code@2.1.295`。

### 工作包 G：数据库约束与迁移

#### P-G1 [P1] 迁移与 models 无自动一致性测试　状态：done
- 假设与排除：✓ `temporary_database` 其实已跑 `command.check`，但只比默认项（不含 server_default 与 CHECK）；✓ upgrade head 与 models 差异为 0（一次通过，没用任何忽略列表）；✗ “0013/0014/0015 原生 SQL 和 0018 条件建表造成漂移”：比较结果证明没有。
- 方案：**A 采用**——真实随机库上 `compare_metadata`，显式开启 `compare_type`、`compare_server_default`、alembic 默认的列/nullable/索引/唯一约束/外键/表增删比较，另自写 CHECK 名称比对。**B 不采用**：靠 `temporary_database` 里已有的 check。
- 测试：`test_schema_consistency.py::test_upgrade_head_matches_models`、`test_check_constraints_match_models`、`test_comparison_detects_model_drift`（负向：往模型副本加列/加索引/删列必须报 `add_column`/`add_index`/`remove_column`）。首次通过没有红（本来没有差异），所以用两种方式证明它能红：负向测试，以及临时往 models 加漂移索引 → `AutogenerateDiffsDetected: add_index ix_task_runs_drift_probe`，还原后绿。

#### P-G2 [P2] 数据库无 CHECK 约束　状态：done
- 做了 9 条：`task_runs.status/mode`、`choice_cards.kind`、`evidence.kind`、`catalog_entries.kind`、`user_memory_facts.scope/status/source`、`bookings` 的 `(payload->>'status')`（不改应用写入路径；payload 缺 status 键时 CHECK 为 NULL 即通过，不拦旧行）。取值来自 domain 的 Literal，无定义的在 models 里定义常量，由测试对照代码核对；迁移里取值是冻结快照，不 import 代码。
- 假设与排除：✓ 旧库有历史取值——`choice_cards.kind` 存着旧值 `travel_details`，`task_runs.mode` 曾是 `offline|live`，所以允许集合保留这些旧值（若直接用代码 Literal，真实旧库升级会被拒）；这一点是邻近测试 `test_choices::test_legacy_card_row_*` 先红才暴露的；✓ 重放兼容——`test_memory_migration` stamp 回 0017 再升级曾 `DuplicateObject`，迁移改为幂等。
- 迁移 0022：先逐表查询非法取值，有就抛 `RuntimeError("<表>.<列> 含未知取值 [...]")` 中止且不改数据；再 `ADD CONSTRAINT ... NOT VALID`，然后 `VALIDATE CONSTRAINT`。
- 测试：`test_schema_constraints.py`——`test_check_values_equal_code_definitions`、`test_database_rejects_unknown_value[8 项]`、`test_booking_status_inside_payload_is_constrained`、`test_upgrade_keeps_existing_rows_of_every_state`、`test_upgrade_refuses_unknown_existing_value_without_changing_data`；红 13 failed（`DID NOT RAISE IntegrityError` 等）→ 绿。
- bookings 状态生成列：不需要改应用写入路径，但目前没有按状态查询的代码，没加。
- 注意：**0022 没有应用到开发库 `travel_agent`**，也没读开发库里是否有非法旧值；若有，迁移会按设计中止并点名表列。

#### P-G3 [P2] 缺索引　状态：done（只加了站得住的 1 个，初审判断修正）
- grep 核对：✗ `task_runs.user_id`（`runs.py:117` 是主键加 `user_id`，`history.py` 总与 `session_id` 联用；EXPLAIN 走主键与 `ix_task_runs_session_id`）；✗ `evidence.user_id/kind`、`bookings.user_id`、`plan_drafts.user_id`、`user_memory_facts.session_id` 同理，`hotel_offer_elsewhere` 的 `kind=…OR payload…` 带不可索引的 OR 分支；✓ `task_runs(session_id, created_at)`：`run_page` 与 `recent_completed` 都按会话取最近 N 条，`ORDER BY created_at DESC LIMIT`。
- 实现：`ix_task_runs_session_id_created_at`（不用 CONCURRENTLY，表小且迁移在事务内）；原单列索引保留（只做加法）。
- EXPLAIN（临时库 7 万行 `task_runs`，其中一个会话 2 万次）：`run_page` Bitmap Scan 取 20010 行再 top-N heapsort 1.49ms → `Index Scan Backward` 22 行 0.030ms；`recent_completed` 1.77ms → 0.035ms。每会话仅约 10 次运行时无明显差别。
- 测试：`test_task_runs_session_created_index_exists`。

#### P-G4 [P2] downgrade 不可用　状态：done（评估后不修，已用测试文档化）
- 原因 VERIFIED：0018 的 downgrade 有意保留 `user_memory_facts`（`test_memory_migration` 断言回退不丢用户记忆），其外键 `fk_user_memory_facts_source_run_id_task_runs` 阻止 0004 删 `task_runs`；0013/0014/0015 同理有意 `pass`。
- 方案：**A 不采用**“每个迁移 downgrade 先删后加对象”：要么让 0018 丢记忆，要么在 0004 对 `task_runs` 做 CASCADE 留下孤立表，违背“迁移只做加法”。**B 采用**：不支持 downgrade 到 base，支持范围写进测试。
- 测试：`test_downgrade_to_0017_and_back_restores_the_same_schema`（head→0017→head，`compare_metadata` 为 0）、`test_downgrade_to_base_is_documented_as_unsupported`（断言 `downgrade base` 报错且含 `user_memory_facts`，将来有人修好它会变红提醒更新文档）。
- 建议：在 migrations/README 补一句“downgrade 只保证到 0017；回退按 revert 提交走”。

#### P-G5 [P2/P3] 只写不读的列　状态：done（评估，未改列）
- `travel_requests.source_turn_id`：生产里只有写入（`persistence/travel.py:23` 写 None，`:71` 写值）；写入的是 `RunContext.run_id`——工具路径是真实 run id，HTTP PATCH 默认构造的 `RunContext` 才是随机 uuid；仅有测试读它（`test_travel.py:331`）。建议：文档标注“溯源，暂无读取方”，或改名 `source_run_id` 加 FK；要删则先去掉写入与该测试再另起迁移 `DROP COLUMN`。
- `users.preferences`：只被置 `{}`，0018 的 downgrade 靠它回退并重建投影，保留理由成立；建议文档化为“遗留，仅供回退”。

#### P-G6 [P2] 外键 ON DELETE、删除能力与清理　状态：done（只出报告，未实现，待决 D2）
- 外键依赖图（全部 NO ACTION，已用临时库实测）与未索引的外键列清单、删会话/账户的安全顺序、注意点（`task_runs` 被 `user_memory_facts.source_run_id` 引用、`memory_forgotten_at` 边界不能失效、`checkpoint_allowed` 校验、墓碑语义）、三个方案（A 手写删除服务 / B 改外键级联 / C 过期清理脚本）见 [数据保留与删除方案](../review/audits/2026-10-18-data-retention-options.md)。

### 第二轮：对抗性复核后的修复（R1–R5）

> 独立复核 Agent 对 14 个方面做了对抗性攻击（只读，复现脚本在 scratchpad 里）：**9 项守住**（A1 并发恢复、A3 重连不无限循环、C1 并发 PATCH、C2/C3 输入边界、E5 写类最小确认、G2 的 CHECK 没有拒绝任何真实生产写入、测试假绿抽查、并行改动无 NUL/行尾混用）；**5 项被攻破**，修复如下。复核者另跑全量回归：2160 通过、5 失败（均为既有的 SDK 真实调用类失败）。

#### P-R1 [P1] 并发 hold 绕过住宿重叠检查　状态：done
- 现象：两个并发 hold（不同酒店、同日期）最终都是 `held`（复现 `assert 2 <= 1`）。
- 根因（VERIFIED）：重叠检查只在 hold 事务里做，那时库里只有 `quoted`，不算占位；`quoted` 提交后会话行锁释放，供应商 hold 在锁外执行，第二个请求看到的仍是 `quoted`。
- 方案：**A 采用**——供应商 hold 成功后、转 `held` 时在会话行锁内**重查重叠**；先变 `held` 的胜出，后到的标 `failed`（reason `duplicate_stay_lost`，error_code `conflict`），返回 409，用户侧不呈现为 `held`。`reject_overlapping_stay` 新增可选 `own_id` 以免自己和自己比较，同一报价重放不受影响。**B 不采用**：让所有 `quoted` 都占位（用户无法同时对比多家报价）；**C 不采用**：整个 hold 期间持锁（供应商调用被串行化、长时间占锁）。
- 测试：`test_booking_integrity.py::test_concurrent_overlapping_holds_leave_exactly_one_held`（红：`held` 有 2 个 → 绿：恰一个 `held`、一个 409 含“重叠”，库里状态 `["failed","held"]`，赢家重放返回同一 booking）。补发订单路径的并发复核 `test_concurrent_confirm_of_reissued_order_makes_one_supplier_order`：3 个并发 confirm、0.3 秒延迟 order，**修复前后都绿**（供应商 order 在 `client_ref` 的 `FOR UPDATE` 锁内先查已有订单，幂等已足够），作为防回归。相关 8 个测试文件共 68 个通过。
- 遗留：mock 供应商没有“释放 hold”接口，输家的供应商 hold 留到自然过期（对用户不可见、也下不了单，因为本地已 `failed`）；真要释放需要给 mock_supplier 加 release 能力。

#### P-R2 [P2] 剩余的 GET 路径仍加会话行锁　状态：done
- 现象：另一连接持有会话 `FOR UPDATE` 时，`GET /plans/{id}`、`/plans/{id}/calendar.ics`、`/plan-drafts/{id}`、`/sessions/{id}/bookings` 在 5 秒内不返回（前三条之前只靠读代码判断，这次实测）；新会话上 `GET /bookings` 还会 `INSERT` 一行 `travel_requests`。其余 GET 本来就不阻塞。
- 方案：**A 采用**——新增独立方法 `TravelService.read_request`（底层是 P-C4 的 `persistence.travel.read_request`）。**B 不采用**：给 `get_request` 加布尔参数 `lock`（容易漏传，调用点看不出语义）。迁移的纯读调用点：`bookings.list`、`plans.get`、`plans.get_draft`、`hotels._request`、`planning.current`、`catalog._load`；读后紧跟写的地方（hold、confirm、`_update`、locks、stage、patch、`business_context`、`planning.validate`、memory、runs、choices 的 create）刻意保持加锁。
- 测试：新增 `test_get_routes_are_lock_free.py`（13 条 GET 参数化，持锁时都 5 秒内返回，另有新会话不建行的用例）；红 5 failed、9 passed → 绿 14 passed；12 个相关测试文件共 142 个通过。
- 遗留：`get_request` 的纯读调用还在工具与演示路径里（`tools/travel.py` 的天气、skill、酒店结果拼装、`agent/demo.py`、`agent/fixture_runtime.py`），不是 HTTP GET，不影响本保证，换成 `read_request` 即可。

#### P-R3 [P2] 登录限流器内存与归一化　状态：done
- 现象：4 万个不同 key 耗时 70 秒（超过 1 万个活跃 key 后每次约 4.5 毫秒，key 不被清）；被全局限流拒绝的请求仍在按 IP 字典留 key；`::ffff:1.2.3.4` 与 `1.2.3.4` 算两个 key；经 Next 代理后 `request.client.host` 是 Next 地址。
- 根因：`SlidingWindow.hit` 每次超限整体重建字典，只保留窗口内 key；IP 与全局两道检查的先后顺序；无归一。
- 方案：**A 采用**——`OrderedDict` 按最近接受时间排序，队首惰性清除过期 key，超过 `max_keys` 淘汰最旧的一个，摊销 O(1)、内存有界（`TokenBucket` 同样改）；新增只读 `check()`，先检查 IP 与全局两道、都通过才提交（任何一道拒绝都不留状态，“被拒绝的请求不计入窗口”语义不变）；`client_key()` 用标准库 `ipaddress` 归一（IPv4 映射地址折成 IPv4，IPv6 按 /64 聚合，非法地址按原字符串回退）。**B 不采用**：heap（要处理 key 的懒删除）、定时全量扫描（仍是 O(n)）、把全局检查放前面（IP 拒绝时仍消耗全局额度）。
- 部署发现（读了已安装的 Next 16.3.8 `proxy-request.js`）：Next 的 rewrites **不会补 `X-Forwarded-For`**，只透传已有的；而 uvicorn 默认 `proxy_headers=True` 且信任 `127.0.0.1`，所以本地客户端伪造的 XFF 会被 uvicorn 采信（应用代码本身不读 XFF）。处理：`backend/server.py` 新增 `proxy_options`，**默认 `proxy_headers=False`**（比 uvicorn 默认更严），只有显式设置 `FORWARDED_ALLOW_IPS` 才开启并只信任这些来源，XFF 由 uvicorn 解析、我们不自己解析。
- 部署说明：不设该变量时完全不读 XFF，所有请求按直连地址计数，安全，但经 Next 代理后所有网页用户共享额度，只适合本地或单用户演示；公网部署需把 `FORWARDED_ALLOW_IPS` 设成 Next 所在地址，且 API 端口只对受信代理开放；**不要设为 `*`**；Railway 私网地址通常动态，需查实际值（待决 D9）。
- 测试：新增 7 个，改动前全部失败（相对耗时不随 key 数增长且字典长度 ≤ `max_keys`、`check()` 不建 key、满额只淘汰最旧、`client_key` 归一、全局拒绝后按 IP 字典不变、映射地址与同 /64 共用额度、`proxy_options` 默认关闭/显式开启）；`rl.py` 4 万 key 从 70 秒降到约 0.03 秒；相关 20 个通过，未改任何已有断言。
- 局限：灌满 1 万个 key 可让别人的额度提前清零（内存有界的代价，彻底解决需外部存储）；IPv6 /64 聚合让同一 /64 的合法用户共用额度；多实例各自计数、重启清零。

#### P-R4 [P1] 来源核对的绕过与性能　状态：done
- 现象：①“不要去大阪，我还是想去京都”声明 city=大阪 被放行；②“周末出发吧”放行 2031-07-19，“明天出发”放行 2099-12-31；③原话“你好”声明 `clear=(city,budget)` 被放行；④“3月5日出发”放行 budget=5；⑤4000–16000 个 "1" 的输入下各字段核对耗时 0.2–1.3 秒（二次方）。
- 假设与排除：adults=5 对“3月5日”的巧合不存在；但发现同类巧合并修了——`2026-11-03人均…` 里的“03人”会被当成 adults=3（改成 `人(?!均|民|气|次|群|家)`），`(\d+)大` 会被“3大阪”误命中（加上下文限定），`\d+(days|nights)` 这条没有 lookbehind 的分支也是二次方。
- 根因：只做子串匹配不看否定语境；相对词只要“原话里没有绝对日期”就为任意日期背书且没有“今天”可参照；clear 无条件保留；金额只要数字相等就算出处；数字 token 可从任意位置起匹配。
- 方案：否定语境——该值的**所有**出现位置都处于否定语境才拒绝，只要有一处肯定出现即通过；相对日期——由相对词推出小窗口，值必须落在窗口内（需注入“今天”，`grounded_fields(..., *, today: date)`），无法解析的说法一律不背书；clear——要有清除/不确定/不限线索，且线索前后 10 字内出现该字段词或“所有/全部/条件”；金额——货币词/符号、万千 k w 单位、“预算 N”三选一，且排除紧跟日期/时间/人数片段的数字；性能——数字 token 只能从数字串起点匹配（lookbehind）。**未采用**：先整体 token 化（改动面更大）。
- 测试：先写测试，只加 `today` 参数未改逻辑时 33 项失败（否定 5、相对日期 11、clear 3、数字巧合 7、性能 7）；实现后 `test_request_grounding.py` 114 项全过（原 41 项全在内）；11 个字段 × 9 种最坏输入（含 16000 字符的 "1"、"一"）耗时上限 0.2 秒；集成测试 `test_r4_bypasses_are_skipped_end_to_end`（注入 today=2026-10-28）；相关 263 个通过。
- **对既有测试的改动**：测试 helper 统一传固定 `today`（2026-10-28，周三）；旧用例“下周五出发，值 2026-11-03”（该日是周二）与新规则矛盾，改成“下周二出发”；旧断言“空原话也放行 clear”与目标矛盾，改为“出发时间还没定”放行、空原话不放行。
- 误拒风险上升（后果只是模型追问一句）：裸“下个月出发”“下个礼拜”被拒；`clear` 必须带线索；纯数字“5000”作预算被拒；否定前缀可能误伤“不要去大阪太累的话，就大阪”。
- 遗留：未做链式否定（“不要去大阪、神户”里的“神户”）与值后否定（“大阪不去了”）；end_date 的“玩 N 天”推算不核对天数与 start 是否一致。

#### P-R5 [P2] 围栏的局部漏洞　状态：done
- 现象：①dict 的**键**从不围栏；②U+E0000–E007F 标签字符（不可见指令走私向量）未剥离；③豁免过宽——纯 ASCII 长指令能冒充 `status`，任意键下的 http URL 整体豁免，`message` 等服务端文案键整体豁免，而 `update_message` 会把 interests、城市等动态文本拼进去且不围栏。
- 假设与排除：✗ “sanitize 本身有缺口”（全角/零宽/嵌套/双向控制/软连字符的同形闭合标签仍被清除，10^6 字符的 ReDoS 用例都在 2 秒内）；✗ “把服务端文案整体围栏”（会让模型把规则当不可信文本，还会因 NFKC 把全角标点变 ASCII）。
- 方案：键——安全键（`^[A-Za-z0-9_.-]{1,64}$`）不变，不安全键改写为 `untrusted_key_N`、值变成 `{"key": 围栏后的原键, "value": ...}`，所以 13 个真实工具的 JSON 结构不变（测试断言不出现 `untrusted_key_`）；不可见字符补全 U+E0000–E007F、E0100–E01EF、2060–206F、180B–180F、FFF9–FFFB、061C、034F、115F/1160、17B4/17B5、3164、FFA0（原有范围保留，U+200D 本来就被剥离，所以家庭 emoji 会拆成单个 emoji，测试如实记录；带 IVS 的汉字异体少一个异体标记）；枚举键（`status`、`provider`、`confidence` 等）值限制 ≤32 字符、至多 3 个单词的 ASCII，ID 类值 ≤64；URL 只在 `url`、`source_ref`、`*_url`、`*_ref` 键下豁免，且只允许 http/https、≤300、无空白和尖括号，其它键下的 URL 一律围栏；服务端文案键保持原样可读，只做去不可见/控制字符、含围栏或角色标记时整段 sanitize、截断到 `FIELD_LIMIT`；`update_message` / `value_label` 增加可选 `quote` 回调（默认 `str`，所以固定文案和既有测试不变，domain 不反向依赖 tools），城市、住宿查询地点、城市段、各类约束项走 `quote=fence`。**未采用**：在 validator、hotels 等 domain 构造处逐个包装（会改变持久化的报告文案、破坏大量断言文案的测试）。
- 测试：`test_fencing.py` 新增 7 个，6 个红（键注入、标签字符、ASCII 指令冒充 `status`、URL 收紧、服务端文案、`update_message` 缺 `quote` 参数）→ 绿；`test_fencing_tools.py` 只增加“真实返回无 `untrusted_key_`”断言；`PLAIN_OK` 名单一项未改，没有扩大。
- 残余风险：枚举键仍可放过 ≤32 字符、≤3 词的指令（如 `ignore_all_instructions`），因为没有按工具的枚举全集校验；`_url`/`_ref` 键下 ≤300 字符 URL 里仍可夹带英文单词序列；验证器 `checks[].message`、酒店 `reasons` 里拼入的景点名/类别/营业时间/`total_reason` 只做 sanitize 级处理，插值的第三方文本中的指令性自然语言不会被拦（要在 domain 构造处包装，会影响持久化的报告文案和 UI，需另行评估）；围栏发生在长度检查之后，标签可能让结果略超 8000 字符上限。
- 备注：R5 说把几个集成测试文件放进同一次 pytest 调用时曾有 11 个用例在 fixture 阶段 ERROR，原因未查清（第一次完整测试里也出现过一个偶发 ERROR）；见 §9。

#### P-R6 [P2] 浏览器端到端验收发现的问题　状态：见下
- **验证方式**：真 Chrome（claude-in-chrome），离线 fixture，未加 `--live`；临时库、API、mock_supplier、Next dev 都是 Agent 自己起的，结束已清理。偏差：API 端口写死 8000（`TRAVEL_API_ORIGIN` 白名单只放行 `http://127.0.0.1:8000`、`http://api:8000` 与 railway.internal，是有意的 SSRF 防护）；默认 Turbopack 的 `pnpm dev` 在本机首页 500（`Cannot find module '@tailwindcss/postcss'`），改 `--webpack` 正常；离线 Run 不到 0.5 秒结束，所以“刷新/停止/断流”是在给工具人为加了 4 秒延迟的 Run 上测的（只在 scratchpad 的启动脚本里，没改仓库）；窗口被锁在约 1062 宽，只看到窄屏页签布局，375 宽用同源 iframe 测量；supplier `--faults` 与真实键盘输入未覆盖（大部分表单用 JS 设值）。
- **通过**：首页与 /articles、/articles/[id]、/plans 都能打开，时间显示东京时区；日期越界与超 30 晚的中文提示可读（“旅行日期需在2000-01-01至2029-10-18之间，收到9999-12-30”、“行程最长30晚，请缩短日期范围”）；特殊字符原样存入但不当 HTML 执行；对话 → 酒店比较 → 行程 → 确认 → /plans → 锁定 → 改程 → 再确认 → `trip-v{n}.ics` → 暂留 → 确认预订 → 订单状态全部走通；第二家同日期酒店返回 409 且提示可读（“该住宿段已有鸭川小筑（模拟）的有效预订（2026-11-10至2026-11-12），日期重叠，不能再暂留另一报价”）；Run 中刷新恢复“处理中”与停止按钮，停止显示“正在停止…”并在终态后恢复且没有 409；停 API 约 10 秒前端退避重连、事件不重复；停约 30 秒后约 20 秒出现“进度连接多次中断…请点击重新连接进度”，点击后恢复；偏好面板未保存文字在 Run 后保留，清除偏好是页内 `alertdialog` 二次确认；375 宽无水平滚动、Tab 可操作主要控件、焦点可见；控制台无应用自身的 JS 报错，所有 4xx/5xx 都是故意操作或停服务造成。
- **发现的问题与处理**：P1 API 端口写死/白名单（有意设计，文档化）；P2 Turbopack 本机首页 500（`dev web` 新增 `--webpack`，见下）；**P3 房间数多于成人数被接受（1 成人 3 房，已修，见下）**；P4 酒店卡片金额格式不一致、P5 过期历史酒店卡“暂留”按钮禁用无原因、P6/P7 与 SSE 无关的错误也带“重新连接进度/读取最新条件”按钮且重连成功后红条残留、P8 失败提示笼统、P9 发送后对话不自动滚到底、P10 锁定使版本 V1→V3 无说明、P12 导航栏无“攻略”入口、P14 无“跳到主内容”——**交给 R6 前端修复**；P11 窄屏对话区偏小、P13 一次截图工具卡死（无法判断是应用还是工具问题）、导航与 Tab 顺序较长——信息项，未处理。
- **P3 修复（主任务）**：C3 的房间数校验要求 `adults`、`rooms`、`child_ages` 三者都已知才检查，UI 提交时 `child_ages` 为空值，所以 1 成人 3 房被放过。改为 `child_ages` 未填时按没有儿童算（`travellers = adults + len(child_ages or ())`，`rooms > travellers` 即 `RequestLimitError`）；`test_rooms_cannot_exceed_travellers` 新增 `{"adults":1,"rooms":3}` 拒绝与 `{"adults":2,"rooms":2}` 通过；相关 102 个通过。
- **P2 处理（主任务）**：本机 Turbopack 的 CSS 子进程起不来是已知问题（此前文档只对 `web-check` 说过），但开发服务器命令没有对应选项。`scripts/dev.py` 的 `web` 子命令新增 `--webpack`（`dev web --webpack` → `pnpm dev --webpack`），与 `web-check --webpack` 对称；`dev` 相关测试 31 个通过。

#### P-R6b [P2] 前端体验修复（R6）　状态：done（视觉与交互未在浏览器里复验）
- **P4 金额格式**：`moneyLabel(amount, currency)` 现在接受 null，null 显示“未知”（不会显示成 0 或空）；酒店卡总价/基础/税/费/套餐下拉/`budget_excess`、行程面板总预算统一用它，币种取卡片自带的 `currency`；`formatYen` 已删。税费未知语义保持（总价 null 仍显示“总价未知”）。**显示变化**：zh-CN 下 JPY 显示为“JP¥”，全站统一，与之前的“¥”略有差异。
- **P5 禁用按钮原因**：新增纯函数 `hotelHoldBlockReason({expired, totalKnown, revisionMatches})`，按优先级返回“报价已过期 / 基于旧条件 / 总价未知”，在按钮下方显示小字并用 `aria-describedby` 关联。
- **P6/P7 错误条按钮**：新增 `src/lib/error-actions.ts`（`ErrorKind = stream | conflict | validation | run | other`，`classifyError` 按状态码分类，`errorActions` 决定按钮集合）；“重新连接进度”只给 stream 类错误且 Run 仍在运行或取消中时显示；校验类 422 不再显示“读取最新条件与行程”；重连读到终态时清掉 stream 类错误。遗留：状态接线靠类型检查，没有 hook/UI 层自动化测试。
- **P8 笼统提示**：`errorExplanation` 新增 `detail` 参数，仅在 code 为 validation 且无更具体封闭原因码时使用，形如“校验未通过：固定演示仅覆盖京都二至三日游。”；过滤条件：含中文、≤60 字、不含换行/`=`/`://`，否则退回原笼统文案（不泄露英文内部 code）。
- **P9 自动滚到底**：`src/lib/scroll.ts` 的 `isNearBottom`（阈值 100px）+ `useStickyBottom`（读者在底部附近时内容变高就跟到底，向上翻阅时不拽回，新一轮强制贴底，`prefers-reduced-motion` 时瞬时）。滚动行为本身没有浏览器验证。
- **P10 版本说明**：`saved-trip.tsx` 每条行程摘要下加一行“锁定或修改都会生成新版本”（纯展示，无测试，版本号逻辑没改）。
- **P12 导航入口**：`src/lib/nav-links.ts` 导航项改成纯数据，新增“攻略与来源”→ `/articles`，按路径前缀判断当前页（文章详情页也高亮并带 `aria-current`）。
- **P14 跳到主内容**：`layout.tsx` 最前面加 `.skip-link`（获得焦点时才可见），三处 `<main>` 加 `id="main-content"` 与 `tabIndex={-1}`。
- 测试：纯函数部分都先红后绿，前端测试从 149 增到 **185 个**（新增 `error-actions`、`scroll`、`nav-links` 三个测试文件，追加 `availability`、`error-explanation`）；`web-check` 全过。
- 未验证：所有视觉与交互行为（滚动、跳到主内容、禁用原因小字样式、导航高亮、金额新格式在行程面板的实际显示）都没有在真实浏览器里复验。

#### P-R5b [回归，主任务修复] R5 收紧标识符上限误围栏 content_version　状态：done
- 现象：完整测试中 `test_catalog_supplement::test_actual_sdk_matches_original_two_search_tool_contract_on_curated_sources` 失败——`source.content_version`（`<sha256>:curation-v1`，76 字符）被 R5 把标识符值上限收紧到 64 后包进了围栏。
- 根因（VERIFIED）：R5 为挡住“长指令冒充标识符”把 `_TOKEN` 上限设为 64，误伤了真实的内容版本。
- 修复：`fencing.py` 新增 `_VERSION = [0-9a-fA-F]{16,64}(?::[A-Za-z0-9._-]{1,32})?`，仅对 `*_version` 键豁免；同样长度的指令冒充版本号（如 `other_version: "ignore-previous-instructions-and-…"`）仍被围栏。
- 测试：`tests/test_fencing.py::test_content_version_hash_with_suffix_is_an_identifier_but_instructions_stay_fenced`；`test_catalog_supplement` 3 个、`test_fencing_tools`、`test_mcp_server`、`test_mcp_hardening` 都通过。
- 教训：收紧安全规则必须跑完整套件——R5 自己的测试都绿，是完整测试抓住了这个回归。

### 工作包 H：文档整理　状态：done
- 见 §7 与 [docs/README](../README.md)。重要结论：新增 P-条目要同步在 [problems.md](problems.md) 加一行（无自动化保证）。

## 9. 验证与交付

分别记录五件不同的事（不合并成“已完成”）。数据日期 2026-10-18，运行环境 Windows 11、PostgreSQL 17（Docker，端口 5434）。

| 验证 | 结果 |
| --- | --- |
| 静态检查 `dev check` | 通过：ruff、ruff format（424 文件）、mypy `--strict`（三平台）、11 条 import-linter 契约、13 份文档入口 |
| 离线单测 + PG 集成 `dev test` | 第二轮完整运行：**2265 通过 / 6 失败**；其中 5 个是**既有问题**（`test_evaluation_variants` 4 个，CLI 2.1.302 不在白名单；`test_travel_sdk_offline[haiku-5-5]` 1 个，在未修改的 HEAD 上同样失败，已用干净 worktree 验证），1 个是 R5 引入的回归（已修，见 P-R5b）。最后一次完整运行见下方“最终结果”。审查前基线：集成 447 通过 / 8 失败 |
| 前端 `web-check` | 通过：类型、lint、**185 个测试**、生产构建（审查前基线 153 通过） |
| 浏览器验收 | 真 Chrome（claude-in-chrome）走通对话 → 确认 → 改程 → 日历 → 暂留 → 订单、刷新恢复、断流重连、偏好面板；14 个问题已处理或归类（§8 P-R6）。**限制**：窗口被锁在约 1062 宽、离线 Run 需人为放慢、`--faults` 与真实键盘输入未覆盖；R6 的视觉与交互改动**未复验** |
| 独立审查 / 对抗性复核 | 6 个领域审查 + 2 个验证 + 1 个对抗性复核（14 方面，9 守住、5 攻破并已修）。**没有做第二轮对抗性复核**（复核修复本身的修复，即 R1–R6 与 P-R5b）——按用户要求在此阶段暂停 |

### 最终结果

- **最后一次完整 `dev test`（含 P-R5b 修复、房间数校验、`dev web --webpack` 之后）：2267 通过 / 5 失败 / 1 跳过 / 4 deselected，349 秒。** 5 个失败全是**既有问题**，不是本批次造成：`test_evaluation_variants` 4 个（本机 CLI 2.1.302 不在白名单，返回 `blocked/auto_compaction_capability`）、`test_travel_sdk_offline[anthropic-claude-haiku-5-5]` 1 个（`provider_error/invalid_assistant_message`；**原因已查清（2026-10-19）**：本机 CLI 2.1.303 对 Haiku 5.5 发 `thinking={'type':'adaptive'}`，`request.py` 的 `_normalize_haiku` 只放行 `disabled` 而拒绝，与另 4 个同属 CLI 版本漂移，修复属 D5 范畴（改守卫/白名单），未改；在未修改的 HEAD `13e3c20` 上同样失败）。
- `dev check`：通过（见上）。`dev web-check`：185 个测试通过、生产构建通过。
- 与批次开始时对比：集成 447 通过 / 8 失败 → 全量 2267 通过 / 5 失败（失败从 8 降到 5，其中 4 个 Windows 事件循环平台缺陷已修，剩下的是 CLI 版本与一个未查清的模型变体）。
- 数据库：开发库 `travel_agent` 未改动；本批次各 Agent 建的临时库都已清理，只留下一个批次之前的评测遗留库 `travel_agent_eval_3234…`（未删，内容不明）。

### 本阶段暂停时的状态

- **所有改动都在工作区，没有提交**（140 多个文件改动 + 50 多个新增）。提交前请按需审阅；行尾 CRLF 会在提交时由 `.gitattributes` 规范化。
- 未应用到开发库 `travel_agent` 的迁移：**0022**（9 条 CHECK + 1 个索引）。升级前建议先在副本上跑一遍；若开发库里有非法旧值，迁移会中止并点名表列。
- 仍需用户决定的事项见 §2；可清理代码见 [可清理代码核查](../review/audits/2026-10-18-cleanup-candidates.md)。
