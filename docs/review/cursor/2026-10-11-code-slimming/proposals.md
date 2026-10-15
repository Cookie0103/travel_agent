# 提案总清单 — Code Slimming (2026-10-11)

> cursor（GLM 5.3）全仓审查产出，交 Codex（gpt-6.1-sol）逐项审批。
> 状态机：待审批 → APPROVE / REJECT / REVISE →（REVISE 改后重审）→ 已执行 → 已验证 → 已提交
>
> **第一轮裁决（2026-10-11，Codex gpt-6.1-sol，全文见 codex-verdicts-round1.md）**：
> REF-001 APPROVE ｜ REF-002 APPROVE（附条件）｜ REF-003 APPROVE ｜ REF-004 APPROVE ｜
> REF-005 APPROVE ｜ REF-006 REVISE（住宿兜底行为差异，修订后重审）｜
> REF-007 REVISE（test_database_eval.py:89-92 指纹复制仍存在，提案证据有误，修订后重审）｜
> REF-008 APPROVE
>
> 审查范围：backend 约 15,400 行（services/api/domain/tools/providers/adapters/persistence/mcp/agent 全部逐文件读）+
> 前端约 6,600 行（lib/components/app 全部逐文件读，api-types.ts 生成文件排除）+
> eval/scripts/mock_supplier 抽查。除下列 8 条外，其余确认「建议保留」。

---

## REF-001 删除 limits.py 三个零引用常量

- 位置：`backend/limits.py:10-12`（`BASE_URL` / `MAX_TOKENS` / `MAX_REQUEST_BYTES`）
- 问题：定义后全项目零引用
- 证据：Grep `BASE_URL|MAX_TOKENS|MAX_REQUEST_BYTES` 全仓库 `*.py`，仅定义处 3 行命中；
  其余命中均为 `LANGFUSE_BASE_URL` / `DATABASE_URL` / `ANTHROPIC_BASE_URL` 等无关环境变量名
- 方案：删除第 10-12 行三常量。同文件其余（`ProbeError`/`Settings`/`price_for`/`load_settings` 等）均有生产引用，不动
- 收益：-3 行，消除「探针常量仍在用」的误导
- 风险：低
- 功能影响：无（零引用）
- 推荐结论：建议修改
- 状态：待审批

## REF-002 删除 Ledger 三个生产零调用的写方法（含测试联动适配）

- 位置：`backend/providers/claude_agent/ledger.py:88-111`（`Ledger.append` / `Ledger.start_flow` / `Ledger.charge`）
- 问题：三方法生产零调用。生产侧引用仅两处：`budget.py:122` 的
  `Ledger(self.legacy).entries()`（只读旧账本）与 `live.py:35` 的 `exclusive`（流程锁）。
  测试侧：`tests/test_protocol_probe.py:76-106` 用 charge/start_flow/append 验证旧探针写路径行为；
  `tests/test_sdk_budget.py:25,121` 用 `Ledger(old).append(Entry(...))` 构造旧账本 fixture 数据
- 方案：删三方法；保留 `Entry`、`read_jsonl`、`append_line`、`exclusive`、`entries`。
  测试联动适配（按用户批准的四条规则：行为还在则改写保留断言；仅验证已废弃行为则删用例并说明；
  构造数据则改用等价直写；绝不删断言/减弱断言/加 skip 凑绿）：
  1. `test_protocol_probe.py`：删除 3 个仅验证已废弃写路径的用例
     （`test_restart_and_new_day_do_not_reset_batch_request_count`、
     `test_currency_budgets_cannot_borrow_from_each_other`、
     `test_success_or_two_flows_prevents_paid_repetition`——它们只经 charge/start_flow 写入）；
     改写 `test_corrupt_ledger_blocks_instead_of_resetting`：`Ledger(path).charge(...)` 改为
     `Ledger(path).entries()`，**保留** `ProbeError match="损坏"` 断言与「文件内容不变」断言
     （坏账本必须拒绝读取的行为仍在生产使用，等价改写）；
     更新模块 docstring 反映剩余内容；import 清理（`UTC`/`datetime`/`timedelta`/`Entry`/`NOW`）。
     **注意**：该文件 19 行有一个 `SETTINGS = Settings(...)` 死常量（定义后全文件无引用），
     按用户「测试代码不精简」的边界默认不动，是否顺带清理请单独裁决
  2. `test_sdk_budget.py:25,121`：`Ledger(old).append(Entry("attempt", "2026-10-03", "CNY", "0.10"))`
     改为等价直写旧格式 JSONL：`old.write_text('{"kind": "attempt", "day": "2026-10-03", "currency": "CNY", "charge": "0.10"}\n', encoding="utf-8")`
     （保持旧账本四字段格式 kind/day/currency/charge）；删 `Entry, Ledger` import
  3. **新增**用例：`Budget.reserve` 读取损坏**旧**账本时拒绝预占、旧账本原字节不变、新账本未写入
     （三断言）。理由：生产路径 `budget.py:122` 在 reserve 内先读旧账本再写入，损坏时应先拒绝；
     现有 `test_corrupt_ledger_refuses_to_reset` 只覆盖新账本损坏，不覆盖 legacy 路径
- 收益：ledger.py -23 行；生产代码不再有无人调用的写路径；「坏账本必须拒绝」的覆盖从新账本
  扩展到旧账本生产路径
- 风险：中（测试改写需保证保留断言等价；新用例需核实 reserve 在写新账本前确实先读旧账本）
- 功能影响：无（删除的是生产零调用路径；读取路径 `entries()` 及损坏拒绝行为保留并加强覆盖）
- 推荐结论：建议修改
- 状态：待审批

## REF-003 删除前端零引用的 modeLabel

- 位置：`apps/web/src/lib/models.ts:14-19`（`export const modeLabel`）
- 问题：全 `apps/web/src` 零引用，仅定义处命中
- 证据：Grep `modeLabel` 全前端，唯一命中为定义行
- 方案：删除该函数（含 Record 查表）。同文件 `offlineOption`/`useModels`/类型导出均在用，保留
- 收益：-6 行
- 风险：低（`npm run typecheck` 兜底）
- 功能影响：无
- 推荐结论：建议修改
- 状态：待审批

## REF-004 activity-drawer 两个导出去掉 export 关键字

- 位置：`apps/web/src/components/activity-drawer.tsx:20`（`export function activityEntries`）、
  `:65`（`export const toolCallCount`）
- 问题：带 export 但全 src 无外部消费者——唯一使用点是同组件内 `RunSteps`（69、73 行）
- 证据：Grep `activityEntries|toolCallCount` 全前端，命中仅定义与组件内部使用
- 方案：去掉两个 `export` 关键字，函数本体与组件内使用不动；不为未使用的公开接口补测试
- 收益：-2 个误导性公开接口
- 风险：低（typecheck 兜底）
- 功能影响：无
- 推荐结论：建议修改
- 状态：待审批

## REF-005 删除 globals.css 零引用的 .money 类

- 位置：`apps/web/src/app/globals.css:64-68`（选择器组 `.tabular, .price, .money`）
- 问题：`.money` 全 src 零引用（已排查动态拼接；`banner-*`/`status-*` 等动态拼接类均排除）。
  同组 `.tabular`（results.tsx:681,744）与 `.price`（results.tsx:147）有真实使用
- 证据：全 CSS 类名逐一 grep 扫描，`.money` 为唯一零引用类
- 方案：选择器组只删 `.money,` 一项，变为 `.tabular,\n  .price {`，声明块
  `font-variant-numeric: tabular-nums;` 保留。历史说明：旧 e2e 曾断言过该类，后随改版脱落
- 收益：-1 行，消除死类
- 风险：低
- 功能影响：无
- 推荐结论：建议修改
- 状态：待审批

## REF-006 交通/住宿口径标签常量化（消除前端 5 处手写映射 + 2 处键校验）

- 位置（全部逐字或语义一致的手写映射）：
  - 交通 `walk/transit/taxi → 步行/公共交通/出租车`：
    `components/trip-panel.tsx:13-17`（Record 查表）、`components/conditions.tsx:245-249`（option 手写）、
    `components/preferences.tsx:139-142`（option 手写）、`lib/condition-patch.ts:104`（`includes` 键校验）
  - 住宿口径 `per_room_night/total → 每房每晚/住宿总额`：
    `components/trip-panel.tsx:134-136`（三元）、`components/conditions.tsx:186-188`（option 手写）、
    `lib/condition-patch.ts:157-160`（校验）
- 后端权威枚举：`backend/domain/travel_request.py:19`（`Transport`）、`:41`（`basis`）；
  后端自己的展示映射在 `backend/domain/condition_labels.py:49`（跨端各自维护，不合并）
- 问题：同一枚举→标签映射前端手写 5 处、校验 2 处；后端新增枚举值时前端需逐处补写，
  漏改处会静默显示 undefined 或被校验拒绝
- 方案：新建 `apps/web/src/lib/trip-options.ts`（项目内先例：`lib/pace.ts` 的 `as const` +
  `conditions.tsx:267-271` 的 `PACES.map()` 渲染）：
  ```ts
  import type { RequestState } from "./api";
  type Transport = NonNullable<RequestState["transport"]>;
  export const TRANSPORTS = [
    { value: "walk", label: "步行" },
    { value: "transit", label: "公共交通" },
    { value: "taxi", label: "出租车" },
  ] as const satisfies readonly { value: Transport; label: string }[];
  export const LODGING_BASES = [
    { value: "per_room_night", label: "每房每晚" },
    { value: "total", label: "住宿总额" },
  ] as const satisfies readonly {
    value: NonNullable<RequestState["lodging_budget"]>["basis"];
    label: string;
  }[];
  ```
  消费点改造：trip-panel 两处改查表（`TRANSPORTS.find(...)?.label`、`LODGING_BASES` 查表）；
  conditions/preferences/conditions 住宿口径改 `map()` 渲染；condition-patch 两处校验改 `find()`
  （只有 find 能把表单字符串收窄为枚举类型）并赋值 `option.value`
- 必须保持不变（语义核查点）：
  - 三处空 option 语义不同，**必须继续手写**：conditions 交通空项「未知」（条件未确认）、
    preferences 空项「无偏好」（长期偏好语义）、conditions 口径空项「未填」
  - 交通值现有 `trim()` 行为保持；住宿口径现状不做 trim，**不顺手改**
  - 选项顺序、全部文案、错误提示不变
- 补测试：非法交通/住宿口径值的失败用例（condition-patch 抛错路径）
- 收益：净 -10 行左右 + 枚举单一来源；`satisfies` 保证值合法性（如实声明：它不保证枚举全覆盖，
  不能自动检测后端新增枚举）
- 风险：中（多处消费点改造，需逐处核对渲染输出不变）
- 功能影响：无（渲染与校验行为字节级不变为目标）
- 推荐结论：建议修改（附上述执行条件）
- 状态：待审批

### 修订版（round 2，按 Codex REVISE 意见修订，待重审）

Codex 指出的问题：`trip-panel.tsx:134-136` 的三元是**双分支兜底**——所有非
`per_room_night` 值都显示「住宿总额」；直接改 `find()` 查表会在未匹配时返回
undefined，改变兜底行为。前端 API 层只是类型断言无运行时校验（api.ts:171）。

修订后的方案（逐条对应 Codex 附加条件①-④）：

1. `apps/web/src/lib/trip-options.ts` 新增：
   ```ts
   import type { RequestState } from "./api";
   type Transport = NonNullable<RequestState["transport"]>;
   export const TRANSPORTS = [
     { value: "walk", label: "步行" },
     { value: "transit", label: "公共交通" },
     { value: "taxi", label: "出租车" },
   ] as const satisfies readonly { value: Transport; label: string }[];
   type LodgingBasis = NonNullable<RequestState["lodging_budget"]>["basis"];
   export const LODGING_BASES = [
     { value: "per_room_night", label: "每房每晚" },
     { value: "total", label: "住宿总额" },
   ] as const satisfies readonly { value: LodgingBasis; label: string }[];
   /** 展示兜底与现三元行为一致：未匹配的值仍显示「住宿总额」。 */
   export const lodgingBasisLabel = (basis: string) =>
     LODGING_BASES.find((option) => option.value === basis)?.label ?? "住宿总额";
   ```
2. 消费点（输出等价性逐一核对）：
   - `trip-panel.tsx`：删 transportLabels Record；交通显示改为
     `TRANSPORTS.find((o) => o.value === request.transport)?.label`——未匹配返回
     undefined，与现 `Record[...]` 行为一致（该处处于 `.filter(Boolean)` 链中，
     undefined 被过滤）；住宿显示改 `lodgingBasisLabel(request.lodging_budget.basis)`
     ——未匹配兜底「住宿总额」= 现三元行为（条件①）
   - `conditions.tsx` 交通 select 与住宿口径 select：非空 option 改
     `TRANSPORTS.map()` / `LODGING_BASES.map()` 渲染；空 option「未知」「未填」手写
     位置在前，其他 option 顺序/值/标签不变（条件②）
   - `preferences.tsx` 交通 select：非空 option 改 `TRANSPORTS.map()`；空 option
     「无偏好」手写保留在前（条件②）
   - `condition-patch.ts` 交通校验（原 104 行区域）：改
     `const option = TRANSPORTS.find((o) => o.value === value); if (!option) throw`
     原文案，赋值 `option.value`（条件④：匹配项收窄）。trim()/等价返回/清空逻辑
     在原分支不动（条件③）
   - `condition-patch.ts` 住宿口径校验（原 157-160 行区域）：改
     `const basis = LODGING_BASES.find((o) => o.value === form.lodging_basis);`
     未找到抛原文案「请选择住宿预算口径。」，赋值 `basis.value`。**不新增 trim**
     （口径现状无 trim，带空白值查表不中即拒绝=现行为）；能力检查/清空/错误先后
     顺序/文案全部在原分支不动（条件③④）
3. 补充验证（`apps/web/tests/condition-patch.test.ts` 追加用例，只断言既有行为，
   覆盖 Codex 条件⑤列的点）：非法交通值抛「请选择有效交通方式。」；交通值带空白
   经既有 trim 后有效；非法口径值抛「请选择住宿预算口径。」；口径带空白仍拒绝
   （无 trim 既有行为）；未修改路径不产生 set/clear；清空路径产生 clear。
   既有测试不删改断言
4. 不做：不添加通用枚举框架；不宣称 satisfies 保证枚举全覆盖（条件④）；
   不改三个空 option（条件②）

修订后状态：待重审

### 第三次修订（round 3，按 Codex 第二轮 REVISE 意见修订，待重审）

Codex 第二轮指出的两个问题与修订：

1. **住宿兜底不得硬编码文案**（条件①为「取常量表中的标签」）：`lodgingBasisLabel`
   兜底改为从表内 total 项取标签：
   ```ts
   export const lodgingBasisLabel = (basis: string) =>
     LODGING_BASES.find((option) => option.value === basis)?.label ??
     LODGING_BASES[1].label;
   ```
   （LODGING_BASES[1] 即 total 项；文案不再重复硬编码）

2. **交通等价性声明修正——明确列为异常数据行为修正**：旧
   `transportLabels[request.transport ?? ""]` 是普通对象查表，会读取继承属性：
   `transportLabels["constructor"]` 返回 `Object.prototype.constructor`（非空，
   渲染为函数源码）、`"toString"` 返回函数、`"__proto__"` 返回对象。新
   `TRANSPORTS.find(...)?.label` 对这些值返回 undefined（被 filter(Boolean)
   过滤为不显示）。**这是有意的行为修正**，不是等价：正常数据流中 transport
   只来自后端 Literal 枚举经 JSON 序列化（walk/transit/taxi/null），异常值不可达；
   旧行为对异常值渲染垃圾内容，新行为不显示。项目内已有同类防护先例
   （tests/condition-patch.test.ts:268「pace editing preserves prototype names」）。
   补充断言（新建 `apps/web/tests/trip-options.test.ts`）：
   - `TRANSPORTS.find((o) => o.value === "constructor")?.label` 为 undefined；
     `"toString"`、`"__proto__"` 同
   - `lodgingBasisLabel("constructor")`、`lodgingBasisLabel("__proto__")` 均
     返回表内 total 标签（兜底路径）
   - 常量表内容断言：TRANSPORTS 三项值/标签、LODGING_BASES 两项值/标签逐项相等

3. **实施顺序（按 Codex 条件⑤+附加条件）**：
   a. 先在旧实现上写并验证六类既有行为断言（追加进 tests/condition-patch.test.ts，
      覆盖：非法交通值抛「请选择有效交通方式。」；交通值带空白经既有 trim 有效；
      非法口径值抛「请选择住宿预算口径。」；口径带空白仍拒绝；未修改路径
      set/clear 皆空；清空路径产生 clear）——旧代码上必须全过（断言的是现状）
   b. 再重构（新建 trip-options.ts + 五个消费点改造）
   c. 重跑 a 的断言仍全过；trip-options.test.ts 新断言全过
   d. 交付：三个 select（conditions 交通/conditions 口径/preferences 交通）与
      trip-panel 住宿展示的改前后 JSX 对比证据 + web-check 结果

4. 其余六项条件（空 option/顺序/文案/trim 差异/find 收窄/不加框架）与 round-2
   修订一致，不再变更

第三次修订后状态：待重审

## REF-007 SCHEMAS 由 DEFINITIONS 派生（消除 16+2 处双份手写）

- 位置：
  - `backend/tools/travel.py:115-207`：DEFINITIONS 里 16 个工具每项手写 `X.model_json_schema()`
  - `backend/tools/travel.py:209-227`：SCHEMAS 再手写一遍 `name → Input 类`（16 项）
  - `backend/tools/search.py:17-26`：SEARCH_DEFINITIONS 2 项（同一模式）
  - `backend/tools/contracts.py:36-42`：`ToolDefinition` frozen dataclass
- 问题：同一信息（工具名→输入类）手写两遍；`SCHEMAS[name]` 在 `travel.py:383` 做
  `model_validate` 校验参数，新增工具漏写 SCHEMAS 项时 KeyError。
  其余消费方：`eval/metrics.py:41,101`、`eval/diagnostics.py:174`（均 `SCHEMAS.get(name)` → `model_validate`，
  与派生后的值语义完全兼容）
- 方案：
  1. `contracts.py` ToolDefinition **末尾**加 `input: type[BaseModel] | None = None`
     （必须带默认值：tests/test_trace_log.py:176、test_mcp_bridge.py:11、test_fencing.py:63
     三处手写位置参数/dict 构造不传该字段）
  2. travel.py 14 处 + search.py 2 处构造补 `input=X`
  3. `SCHEMAS = {d.name: d.input for d in DEFINITIONS if d.input is not None}`
     （保留名字与类型 `dict[str, type[BaseModel]]`；DEFINITIONS 展开了 SEARCH_DEFINITIONS，
     派生自然包含全部 16 项）
- 关键耦合（必须同步处理，缺一不可）：
  1. `eval/run.py:387-390` `schema_fingerprint` 用 `asdict(d) + json.dumps` 序列化整个
     ToolDefinition——`input` 是 type 对象不可 JSON 序列化，**必须在该函数内排除 `input` 键**
     （如序列化前 `{k: v for k, v in asdict(d).items() if k != "input"}`）。
     `eval/compare.py:192` 是 import 复用，不用改。
     **注意**：本次审查 grep 确认 `tests/` 内已无指纹实现复制（`asdict|schema_sha256|fingerprint`
     在 tests/ 零命中；上次会话记录的 test_database_eval.py:90 复制已不存在）——只需改 eval/run.py 一处
  2. **改动前先保存各评测工具集旧指纹**：写临时脚本对 TRAVEL_DEFINITIONS / SEARCH_DEFINITIONS /
     评测变体集合（evaluation_definitions 各 variant）逐集计算当前 schema_fingerprint 存档；
     改完后逐一比对**必须完全一致**，不一致即回退排查
  3. 保留 DEFINITIONS 顺序（改序会变指纹、改变模型可见工具排列）
  4. `mcp/server.py:29-33` READ_ONLY 按 `definition.name` 过滤、`travel.py` `live_definitions`
     同样按 name——均不经 SCHEMAS，不受影响
  5. `tests/integration/test_travel_tools.py:56-57` 锁定 DEFINITIONS/SCHEMAS 名单一致且
     `d.schema == SCHEMAS[d.name].model_json_schema()`——派生后天然满足
- 收益：SCHEMAS 19 行手写变 1 行派生；新增工具只写一处；漏改 KeyError 风险消除；指纹含义不变
- 风险：中（指纹耦合是主要风险，以「旧指纹逐一比对一致」为完成标准）
- 功能影响：无（指纹不变 = 评测绑定不变；SCHEMAS 值的运行时语义不变）
- 推荐结论：建议修改（附上述执行条件）
- 状态：待审批

### 修订版（round 2，按 Codex REVISE 意见修订，待重审）

**证据修正（撤回原方案错误）**：原方案称「tests/ 内已无指纹实现复制」是错误的。
`tests/integration/test_database_eval.py:89-92` 仍独立计算完整 `asdict(d)` 指纹并与
manifest 比对（本会话 Grep 工具对 `tests/**/*.py` glob 过滤存在漏报，已由直接读文件
与 Codex AST 检查双重证实）。原方案「只改 eval/run.py 一处」不成立。

修订后的方案（逐条对应 Codex 附加条件①-⑦）：

1. `contracts.py` ToolDefinition 在**所有现有字段之后**追加
   `input: type[BaseModel] | None = None`（带默认值兼容三处测试手写构造：
   test_trace_log.py:176、test_mcp_bridge.py:11、test_fencing.py:63）（条件①）
2. `tools/travel.py` 14 处 + `tools/search.py` 2 处构造补 `input=X`，16 项全部绑定；
   `SCHEMAS = {d.name: d.input for d in DEFINITIONS if d.input is not None}`，类型
   `dict[str, type[BaseModel]]` 不变；不做「漏项后靠过滤悄悄缩小注册表」的写法
   ——派生前先断言全部 16 项 input 非空（条件①）
3. `eval/run.py:387-390` `schema_fingerprint`：序列化前排除 `input` 键；**只排除
   该键**，其余六字段及原 sort_keys、json.dumps 默认参数、编码、SHA-256 算法全部
   不变（条件②）
4. **`test_database_eval.py:89-92` 联动适配（条件③）**：测试内的期望指纹计算同步
   排除 `input` 键（如 `json.dumps([{k: v for k, v in asdict(d).items() if k != "input"} for d in DEFINITIONS], sort_keys=True)`），
   保持**独立内联计算**，不 import 被测 `schema_fingerprint` 生成期望值；第 92 行
   `assert metadata["schema_sha256"] == expected` 及其余断言原样保留
5. **指纹存档比对（条件④）**：改动前用你提供的命令保存 16 个命名集合
   （search、travel、7 个 variant × 2 个 database 取值）的 schema_fingerprint
   存档到本记录目录；改后重跑逐一比对，**逐行比较 16 个集合**（非去重哈希），
   完全一致才算完成；禁止更新任何旧预期接受漂移
6. 保留 DEFINITIONS 顺序（不重排定义去匹配 SCHEMAS 顺序）；描述/schema/kind/
   超时/结果长度不动（条件⑤）；验证 `repair_definitions`/`live_definitions` 经
   `dataclasses.replace` 派生后 input 字段仍在（条件⑥）
7. 保留 `test_travel_tools.py:56-57` 名单/schema 一致性断言（条件⑥）；
   `mcp/server.py` READ_ONLY 与 `live_definitions` 按名过滤，不受影响
8. 验证（条件⑦ + 你给的命令清单）：`dev.py check`；专项
   `pytest tests/test_mcp_bridge.py tests/test_fencing.py tests/test_trace_log.py
   tests/test_travel_search.py tests/test_evaluation_variants.py tests/test_eval.py
   tests/test_eval_metrics.py tests/test_eval_compare.py tests/test_diagnostics.py
   tests/integration/test_travel_tools.py tests/integration/test_database_eval.py`；
   全量 `dev.py test`（4 基线失败逐一相同）；16 集合指纹比对输出存档

修订后状态：待重审

## REF-008 更新 dev.py eval_dev 的过时 docstring（可选小项）

- 位置：`scripts/dev.py:115-119`（`eval_dev` docstring：「M0.6 实现前明确拒绝评测入口，不伪造结果」）
- 问题：M0.6 早已实现（eval/run.py 存在且在用）；守卫的真实语义现在是
  「eval/run.py 文件缺失时明确拒绝」。测试 `tests/test_dev.py:136-147`
  （`test_unimplemented_evaluation_fails_without_starting_a_process`）通过 tmp_path 构造
  文件缺失场景覆盖该守卫——**守卫逻辑有测试覆盖，不能删**
- 方案：仅更新 docstring 文案以反映现状（如「eval 入口缺失时明确拒绝，不伪造结果」），
  守卫逻辑与测试不动
- 收益：文档准确性（消除「等待 M0.6」的过时表述）
- 风险：低
- 功能影响：无
- 推荐结论：可选修改（若你要求该文案一字不动，则放弃本项）
- 状态：待审批

---

## 建议保留的区域（无提案，审查确认干净）

- backend services/api（约 4,100 行）：薄入口 + 用例层，复用良好，零死代码
- backend domain（18 文件约 3,300 行）：纯规则模型，零冗余
- backend providers/claude_agent 除 ledger 三方法外（约 2,700 行）：进程隔离/预算/看门狗/检查点
  全部在用
- backend adapters/persistence/mcp/agent（约 3,600 行）：零发现
- `persistence/temporary.py:46-47` 的双 `command.upgrade(config, "head")`：
  docs/tasks/M1.md 验收规格明确要求「重复迁移幂等」，非冗余
- 前端 lib/components 除上列 4 条外（约 6,400 行）：干净
- `eval/`/`scripts/`/`mock_supplier/`：评测基础设施，抽查确认在用

## 验证关卡（每批执行后）

- backend：`uv run python scripts/dev.py check`；`uv run python scripts/dev.py db-up` 后
  `uv run python scripts/dev.py test`
- web：`npm run typecheck` / `npm run lint` / `npm test`
- 已知基线失败（不修不删断言，报告说明）：`tests/integration/test_evaluation_variants.py`
  4 个 SDK capability 协商环境失败