# 执行流水 — Code Slimming (2026-10-11)

> 已归档（2026-10-18 整理）：早期里程碑/批次/外部审查材料，保留原文不改。当前状态以[批次索引](../../../../plans/README.md#批次索引)为准；归档目录见 [archive/README](../../../README.md)。

> 按时间顺序追加。每批记录：改动明细 / 测试适配（及理由）/ 验证命令与结果 / commit hash。

## 2026-10-11 基础设施

- 建 worktree `/Users/ke.chen/開発/agent/travel_agent-slimming`（基于 `3b9924b`，
  新分支 `batch/2026-10-11-code-slimming`），主检出（frontend-restyle）零影响
- 建 `docs/review/cursor/2026-10-11-code-slimming/` 记录骨架（本目录）
- Phase 1 分区审查启动（多 agent 并行，只读）：7 个审查 agent 分区为
  S=backend services/api、D=backend domain/tools、P=backend providers/claude_agent、
  A=backend adapters/persistence/mcp/agent、W=前端 lib、C=前端 components/app、
  X=eval/scripts/mock_supplier/根配置；各自对照 commerce-agents，要求逐条附 grep 证据
- 用户确认长程任务自主推进模式：commit 不再逐次确认；Codex 审批与全量验证关卡不变；不 push

## 2026-10-11 Phase 1+2 完成（主会话直读审查）

- Task 后台/前台派发各一次均未返回句柄（通道故障），改为主会话逐文件直读 + Grep 验证：
  后端 15,400 行全读、前端 6,600 行全读（api-types.ts 排除）、eval/scripts/mock_supplier 抽查
- 审查结论：8 条实质发现（S-1/D-1/P-1/W-1/W-2/C-1/C-2/X-1），整理为 REF-001~008 写入
  `proposals.md`；其余区域确认「建议保留」（详见 proposals.md 末节）
- 关键核实：tests/ 内已无指纹实现复制（上次会话记录的 test_database_eval.py:90 已不存在）；
  test_dev.py:136-147 确认在测 eval-dev 守卫；test_protocol_probe.py:19 SETTINGS 死常量确认存在
- 提案已交 Codex 审批（codex exec --sandbox read-only）

## 2026-10-11 基线复证（改动前）

- worktree 补齐运行环境：`uv sync --locked`、复制主仓库 `.env`（gitignore 内，不进提交）；
  PG 复用主仓库已起的 `travel_agent-postgres-1`（127.0.0.1:5434）
- `dev.py check` 全绿；`dev.py test` 基线：**4 failed, 1585 passed, 1 skipped, 4 deselected**
- 4 个基线失败 node ID（与上次会话记录一致，根因 `('blocked', 'auto_compaction_capability', 0, [])`，
  断言于 tests/integration/test_evaluation_variants.py:270，SDK capability 版本白名单环境问题）：
  1. `test_actual_sdk_advertises_variant_and_keeps_trip_and_preferences_unchanged[no_compaction]`
  2. `test_actual_sdk_advertises_variant_and_keeps_trip_and_preferences_unchanged[baseline_b2]`
  3. `test_native_compaction_control_with_same_usage_and_trip[no_compaction]`
  4. `test_native_compaction_control_with_same_usage_and_trip[baseline_b2]`
- web 依赖 `npm install`（424 包）；web 三关基线全绿（typecheck/lint/test 134 pass）

## 2026-10-11 第一批实施（REF-001+003+004+005+008，均已 APPROVE）

- REF-001：`backend/limits.py` 删 BASE_URL/MAX_TOKENS/MAX_REQUEST_BYTES 三常量（-3 行）
- REF-003：`apps/web/src/lib/models.ts` 删 modeLabel 完整函数（14-21 行，-8 行）
- REF-004：`apps/web/src/components/activity-drawer.tsx` activityEntries/toolCallCount 去 export（-2 关键字）
- REF-005：`apps/web/src/app/globals.css` 选择器组删 `.money` 项（-1 行，.tabular/.price 保留）
- REF-008：`scripts/dev.py` eval_dev docstring 改为「评测入口文件缺失时明确拒绝，不伪造结果。」
- 验证：`dev.py check` 全绿；`dev.py test` **4 failed（node ID 与基线逐一相同）+ 1585 passed**；
  web typecheck/lint/test 全过（134 pass）。改动不涉及测试与 prompt 文本
- 净变化：5 文件，-14 行

## 2026-10-12 第一批 Codex 验收

- **APPROVE**（验收通过）：五个文件均符合附加条件，无意外文件，测试未改动。
  裁决存档 /tmp/codex-batch1-accept.md（要点已并入本目录记录）

## 2026-10-12 第二批实施（REF-002，APPROVE 附条件执行）

- 生产：`backend/providers/claude_agent/ledger.py` 删 `Ledger.append/start_flow/charge`
  三方法（-23 行）；保留 Entry/read_jsonl/append_line/exclusive/entries；模块与类
  docstring 校正为「只读边界与流程互斥」；import 清理（asdict/UTC/Decimal 删，
  **datetime 保留**——entries() 第 77 行 strptime 在用，首轮误删后由 check 捕获修正）
- `tests/test_protocol_probe.py`：删 3 个仅验证已废弃写路径的用例（逐项理由：
  test_restart_and_new_day.../test_currency_budgets.../test_success_or_two_flows...
  均只经 charge/start_flow 写入，写路径随生产方法删除而废弃）；改写
  test_corrupt_ledger_blocks_instead_of_resetting 为 `Ledger(path).entries()`，
  保留 match="损坏" 与内容不变断言；模块 docstring 更新；import 清理
  （datetime/timedelta/Entry/NOW 删）；**SETTINGS 死常量按 Codex 裁决保留**
- `tests/test_sdk_budget.py`：两处 `Ledger(old).append(Entry(...))` 改为直写旧格式
  JSONL（四字段 kind/day/currency/charge、金额字符串、UTF-8、行末换行，与原
  append 字节一致）；删 Entry/Ledger import；**新增**
  test_corrupt_legacy_ledger_blocks_reserve_without_writing（三断言：reserve 抛
  match="损坏" / 旧账本原字节不变 / 新账本未创建；有效预算 Decimal(5) 确保到达
  budget.py:122 旧账本读取）
- 验证：check 全绿；专项 51 passed；全量 **4 failed + 1583 passed**（4 个失败 node ID
  与基线逐一相同）。数字核算：1585-3 删+1 增=1583 ✓
- 偶发事件如实记录：第一次全量曾出现 1 个基线外失败
  （test_conversation_state.py::test_new_same_kind_goal_after_privacy_tombstone_uses_new_user_prompt），
  单跑通过、重跑全量通过，判定为顺序依赖 flaky，与 REF-002 改动无关（该用例不涉及
  ledger/budget）；完整日志 /tmp/batch2-test-full.log

## 2026-10-12 第二批 Codex 验收（两轮）

- 第一轮 **REJECT**：两处 `write_text` 未指定 `newline="\n"`，Windows 写 CRLF 破坏与
  原 `append_line`（固定 LF）的字节一致性。实施方补上 `newline="\n"` 后 amend
  （e7092e6），专项 51 passed 重验
- 第二轮 **APPROVE**：两处已明确 newline；内存字节核对一致；①②④⑤符合；既有断言保留

## 2026-10-12 REF-006/007 第二轮重审（Codex round-2 verdicts）

- **REF-006 再次 REVISE**（第三次修订要求）：①住宿兜底不得硬编码文案，改为取表内
  total 项标签（如 `LODGING_BASES[1].label`）；②实施方「交通未匹配均维持现状」的等价性
  声明不成立——旧 `Record` 查表会读取继承属性（`constructor`/`toString`/`__proto__`
  的旧输出非空），新 find 输出为空；须列为明确的异常数据行为修正并补充断言后重审；
  ③实施时先在旧实现上验证六类追加断言再验证重构后通过；④提交三个 select 与住宿展示
  的前后对比证据及 web-check 结果
- **REF-007 APPROVE**（附执行条件）：原子提交；派生前断言必须实际执行（不能仅靠
  过滤漏项）；16 集合指纹带基线 SHA 保存、改后逐项完全一致；补齐 db-up 与
  tests/integration/test_evaluation_variants.py 验证；4 项基线失败记录准确 node ID
  并证明改后相同（已具备：见上方基线记录节）

## 2026-10-12 REF-006 第三轮重审 + 第三批实施

- Codex round-3 **APPROVE**（附加条件：常量表断言固定顺序/值/标签、LODGING_BASES[1]
  为 total、异常值测试用 string 类型输入避免 TS2367、交付前后对比与完整 web-check、
  验收记录明确交通异常值行为修正）
- 实施顺序（按条件）：
  a. **先在旧实现上写六类既有行为断言**并验证：tests/condition-patch.test.ts 追加
     4 个用例（非法交通值抛原文案 / 交通带空白经既有 trim 归一 / 非法与带空白口径值
     不 trim 拒绝 / 未修改不提交且清空走 clear），旧代码上 138 pass 0 fail ✓
  b. 重构：新建 `src/lib/trip-options.ts`（TRANSPORTS/LODGING_BASES as const
     satisfies + lodgingBasisLabel 兜底取 LODGING_BASES[1].label）；trip-panel 删
     transportLabels Record、交通显示改 find、住宿显示改 lodgingBasisLabel；
     conditions 交通/口径 select 非空 option 改 map()（空 option「未知」「未填」手写
     保留在前）；preferences 交通 select 同改（「无偏好」手写保留）；condition-patch
     交通校验改 find+option.value 收窄（trim/等价/清空留在原分支）、口径校验改
     find+basis.value（不新增 trim、能力检查/清空/错误顺序不动）
  c. 新建 `tests/trip-options.test.ts`（常量表逐项断言 / 已知值查表 / 异常值
     constructor/toString/__proto__：交通 find 为 undefined、lodgingBasisLabel 兜底
     取表内 total 标签；string 类型输入无类型抑制）
  d. 验证：web 四关全绿（lint 含 Prettier、test **141 pass 0 fail**、typecheck、
     build）；`npm run format`（项目自带 script）统一格式后重验
- **前后对比证据**（Codex 要求）：
  1. conditions 交通 select：改前手写 4 option（未知/walk=步行/transit=公共交通/
     taxi=出租车）→ 改后「未知」手写 + TRANSPORTS.map()，值/标签/顺序逐一相同
  2. conditions 口径 select：改前手写 3 option（未填/per_room_night=每房每晚/
     total=住宿总额）→ 改后「未填」手写 + LODGING_BASES.map()，逐一相同
  3. preferences 交通 select：改前手写 4 option（无偏好/walk/transit/taxi）→
     改后「无偏好」手写 + map()，逐一相同
  4. trip-panel 住宿展示：旧三元（per_room_night→每房每晚，其余一律住宿总额）→
     lodgingBasisLabel（已知值查表；未匹配兜底取表内 total 标签，与旧三元兜底一致）
  5. trip-panel 交通展示：旧 Record 查表→find。已知值（walk/transit/taxi/null/
     undefined/""）输出逐一相同；**异常值行为修正（如实声明）**：
     constructor/toString/__proto__ 在旧 Record 下渲染继承属性垃圾内容，新 find
     返回 undefined 被过滤为不显示；正常数据流（后端 Literal 枚举经 JSON 序列化）
     不可达异常值

## 2026-10-12 第三批 Codex 验收 + 第四批实施（REF-007）

- 第三批验收 **APPROVE**（Codex 在临时副本复验：旧实现 138 pass、新实现 141 pass，
  lint/typecheck/build 全过；问题清单无）
- REF-007 实施（原子提交，按附加条件）：
  1. `contracts.py`：ToolDefinition 所有现有字段之后追加
     `input: type[BaseModel] | None = None`（带默认值，三处测试手写构造不受影响）
  2. `tools/search.py` 2 处 + `tools/travel.py` 14 处构造补 `input=X`（16 项全部绑定）
  3. `tools/travel.py` SCHEMAS 改派生：模块级 `assert all(...input is not None...)`
     先行断言 + 循环填表（断言真实执行，不靠过滤缩小注册表）；19 行手写映射变派生；
     `PlaceSearchInput` import 随派生失去用途，由 ruff F401 捕获后清除
  4. `eval/run.py` schema_fingerprint：序列化前排除 `input` 键，其余六字段/
     sort_keys/json 参数/编码/SHA-256 不变
  5. `tests/integration/test_database_eval.py` 内联期望指纹同步排除 `input` 键：
     保持独立内联计算（未 import 被测 schema_fingerprint），第 92 行断言原样
- **16 集合指纹比对**：改动前基线存档于本目录 `schema-fingerprints-baseline.json`
  （基线 SHA 1ac64de）；改动后逐行 diff **完全一致**（search/travel/7 variants ×
  2 database 取值，16/16）✓
- 验证：check 全绿（其中 assert-all 行格式由 ruff format 捕获后改单行）；
  db-up Healthy（worktree 用 `COMPOSE_PROJECT_NAME=travel_agent` 复用主仓库 compose
  项目与容器，避免 5434 端口冲突——数据库可用性同时由测试全绿证明）；
  专项清单（mcp_bridge/fencing/trace_log/travel_search/eval 系列/travel_tools/
  database_eval/evaluation_variants）：4 failed（基线相同 node ID）+ 138 passed；
  全量：**4 failed + 1583 passed + 1 skipped + 4 deselected，与基线完全一致**
## 2026-10-12 第四批 Codex 验收 + 任务总结

- 第四批验收 **APPROVE**（Codex 独立只读复算：16 项输入绑定与父提交 SCHEMAS 一致、
  原六字段及定义顺序不变、16 组指纹完全一致、live/repair 派生保留 input、测试期望
  仍独立内联计算；问题清单无）

### 任务总账

- 提交序列（`batch/2026-10-11-code-slimming`，基线 `3b9924b`，未 push）：
  - R0 记录提交 ×5（骨架/审查记录/裁决/验收/指纹基线）
  - **R1** `9e36728` REF-001+003+004+005+008（已验收）
  - **R2** `e7092e6` REF-002（首验 REJECT newline 问题，修复后验收）
  - **R3** `51164b5` REF-006（三轮重审后验收）
  - **R4** `0cfeac2` REF-007（验收）
- 代码+测试总变化：20 文件，+223/-133。构成：
  - 生产净删：limits 三常量(-3)、ledger 三方法与 import(-31)、modeLabel(-8)、
    .money(-1)、drawer export(-2)、dev docstring、transportLabels Record 与
    手写标签多处收敛、SCHEMAS 手写 19 行变派生
  - 结构改善：工具名→输入类单一来源（16 项断言全绑定）；交通/住宿口径标签单一
    来源（trip-options 表 + 兜底语义保持）；新增 Budget.reserve 损坏旧账本
    生产路径覆盖
  - 测试：删 3 个废弃写路径用例（理由逐项见上）；改写 1 个（等价）；fixture 直写
    2 处（字节一致）；新增 trip-options 测试与 condition-patch 先行断言、
    corrupt-legacy 用例
- 全程行为不变性证据：4 个基线失败 node ID 在每批前后完全一致；16 集合指纹逐行一致；
  web 134→141 测试全过；backend 1583 passed 每批一致
- 验收中暴露并修复的实施失误（如实记录）：datetime import 误删（check 捕获）、
  write_text 缺 newline（Codex 验收捕获）、assert 格式与 F401（ruff 捕获）、
  npm 生成 package-lock.json 误入首提交（amend 移除）
- 未动：tests/test_protocol_probe.py SETTINGS 死常量（Codex 裁决保留，测试不精简
  边界）；4 个 SDK capability 基线失败（环境问题，未修未删断言）；prompt 文本零改动

## 2026-10-12 CI 等价验证补全（docker-demo）

- 用户询问 CI 通过性后补跑 `.github/workflows/check.yml` 中唯一未本地验证过的
  docker-demo job（stack-up + smoke_demo + 重启 + --verify）
- 首跑失败诊断：`scripts/stack.py` 用固定 compose 项目名 `travel-agent-demo`，
  demo PG 数据卷跨仓库共享，密码存 `.cache/demo.env`；worktree 的 .cache 为新生成
  随机密码，与既有卷的旧密码不匹配 → bootstrap 连接 FATAL。**纯环境问题，
  与分支代码无关**（CI 为全新容器+全新卷+新密码，不存在该场景）
- 对齐主仓库 `.cache/demo.env` 后重跑：stack-up 三容器 Healthy，
  smoke_demo 三流程通过（比较酒店/生成行程/修改第二天下午，core_flows passed）；
  重启幂等 + `--verify`（read_only）同样 passed；stack-down 清理完毕
- **CI 三 job 本地等价验证结论**：
  1. python（check+test，PG 17 service）：本地全绿；4 个本地基线失败不会出现在 CI——
     CI 固定安装 claude-code@2.1.295（恰在 runtime.py 版本白名单内），本地失败是
     本机 CLI 版本环境问题
  2. web（typecheck/lint/test/build，pnpm 11.19 + Node 24）：本地全绿
     （本地用 npm 安装依赖，命令相同）
  3. docker-demo：本地等价全流程 passed
- 行数总账（git numstat，不含记录文档）：
  - 生产代码（backend/eval/scripts/apps/web/src）：+92 / -95，**净 -3 行**
  - 测试（tests/ + apps/web/tests/）：+131 / -38，净 +93（新增覆盖）
  - 构成说明：纯死代码删除约 -50 行（ledger 三方法与 import、modeLabel、
    limits 三常量、transportLabels Record、.money、drawer export）；其余删除为
    被替换的旧写法（SCHEMAS 手写 19 行、手写 option 标签、三元与 includes 校验），
    换来的新增为结构性成本（trip-options 常量表 +20、input= 绑定 16 处、
    两处指纹排除 input 逻辑、map() 渲染展开）——核心收益是单一来源与防漏改，
    不是行数
