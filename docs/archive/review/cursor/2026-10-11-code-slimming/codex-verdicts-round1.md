## REF-001

> 已归档（2026-10-18 整理）：早期里程碑/批次/外部审查材料，保留原文不改。当前状态以[批次索引](../../../../plans/README.md#批次索引)为准；归档目录见 [archive/README](../../../README.md)。

- 裁决: APPROVE
- 理由: 全仓 Python 精确符号检索中，三个常量仅在 backend/limits.py:10 至第 12 行定义，没有导入或读取点。其他配置、价格和预算接口仍有生产消费者。
- 附加条件: 仅删除这三个常量，不扩大到 `Settings`、价格、预算校验或环境变量配置。

## REF-002

- 裁决: APPROVE
- 理由: 三个写方法位于 ledger.py:88 至第 111 行；全仓 Python 检索确认调用仅来自提案列出的测试。生产预算路径仍在 budget.py:122 读取旧账本，实际新账本写入到第 162 行才发生。三个拟删除用例确实只验证旧写路径，见 test_protocol_probe.py:73。两处 fixture 写入和新账本损坏测试也已核实，见 test_sdk_budget.py:25、第 121 行及第 68–74 行。
- 附加条件: ① 保留 `Entry`、`entries`、`read_jsonl`、`append_line`、`exclusive`；只清理由方法删除直接造成的无用 import，并校正相关生产 docstring。② 仅删除提案列出的三个废弃写路径用例，逐项记录理由；损坏账本用例改读 `entries()`，保留异常匹配和内容不变断言。③ 两处 fixture 必须保持原四字段、金额字符串、UTF-8 和行末换行，其余断言不动。④ 新增旧账本损坏的 `Budget.reserve` 验证：匹配损坏异常、旧文件原字节不变、新账本未创建；使用有效预算以确保确实到达旧账本读取。⑤ **不批准顺带删除 `SETTINGS`**；test_protocol_probe.py:19 的常量及其 `Settings` import 保留。

## REF-003

- 裁决: APPROVE
- 理由: 全前端源码及测试检索，`modeLabel` 只有定义命中。实际完整定义是 models.ts:14 至第 **21** 行，提案的结束行号不准确；`useModels` 从第 23 行开始。
- 附加条件: 删除完整函数表达式及专属查表；保留 `Mode`、`ModelOption`、`offlineOption`、`useModels`，不修改模型选择行为或测试。

## REF-004

- 裁决: APPROVE
- 理由: 全前端检索没有外部消费者。两个符号定义在 activity-drawer.tsx:20、第 65 行，实际调用仅在同文件第 69、73 行。
- 附加条件: 只移除两个 `export`；保留函数体、`RunSteps` 导出和全部渲染文案，不调整测试。

## REF-005

- 裁决: APPROVE
- 理由: 前端源码和测试中没有 `.money` 类消费者；源码唯一相关命中是 globals.css:66，另一个 `money` 命中只是英文注释。同组 `.price` 实际用于 results.tsx:147，`.tabular` 用于第 681、744 行。
- 附加条件: 仅删除该选择器项；保留 `.tabular`、`.price`、声明块及所在 CSS 层，不修改测试或其他样式。

## REF-006

- 裁决: REVISE
- 理由: 重复映射和校验确实存在，见 trip-panel.tsx:13、conditions.tsx:186、第 245–249 行、preferences.tsx:139，以及 condition-patch.ts:104、第 157–161 行。但住宿展示目前对所有非 `per_room_night` 值都显示“住宿总额”，见 trip-panel.tsx:134；直接改成可返回 `undefined` 的查表会改变兜底行为。前端 API 只是类型断言，没有运行时响应校验，见 api.ts:171，不能仅凭 TypeScript 类型忽略该差异。
- 附加条件: ① 修订住宿展示方案：未匹配时继续取常量表中的“住宿总额”标签，不引入新的空白、“未知”或异常。② 保留三个空 option 的位置和文案，以及其他 option 顺序、值和标签。③ 查表校验必须留在原分支内：交通保留 `trim()`、等价值直接返回和清空逻辑；住宿口径不新增 `trim()`，保留能力检查、清空、错误先后顺序及错误文案。④ 类型收窄使用匹配项的 `value`；不添加通用枚举框架，也不宣称 `satisfies` 能保证枚举全覆盖。⑤ 既有测试不精简、不删改断言；补充验证只能断言既有行为，须覆盖非法值、交通空白规范化、住宿口径带空白仍拒绝、未修改和清空路径。⑥ 修订方案后重审，当前不允许直接实施。

## REF-007

- 裁决: REVISE
- 理由: 我用只读 AST 检查确认：search 有 2 项、travel 本地有 14 项，合计 16 项，现有定义与 `SCHEMAS` 的名称→输入类映射完全一致，见 travel.py:115、第 209–226 行及 search.py:16。派生方向合理。但提案声称测试没有指纹复制是错误的：test_database_eval.py:89 至第 92 行仍独立计算完整 `asdict(d)` 指纹。新增类型字段后，生产 eval/run.py:387 和该测试都会遇到 JSON 序列化问题，不能只改生产函数。
- 附加条件: ① 在 `ToolDefinition` **所有现有字段之后**追加带默认值的 `input`；保留原构造方式和字段语义。16 项全部绑定正确输入类，派生结果保留明确类型；不得漏项后靠过滤悄悄缩小注册表。② `eval/run.py` 序列化前只排除 `input`，保留其他六字段及原排序、JSON 默认参数、编码和 SHA-256 算法。③ 将上述测试复制点纳入必要联动适配：仍独立按原六字段计算预期指纹，保留第 92 行比较及其他断言；**不要改成调用被测 `schema_fingerprint` 来生成预期值**。④ 改动前保存 search、travel，以及每个 variant 在两个 `database` 取值下的指纹；改动后逐项完全一致，禁止更新旧预期来接受漂移。⑤ 保留 `DEFINITIONS` 顺序、描述/prompt、schema、kind、超时和结果长度；不要为匹配旧 `SCHEMAS` 顺序而重排定义。两者当前顺序本就不同，现有生产消费者使用按键校验，见 travel.py:383、metrics.py:41、diagnostics.py:174。⑥ 保留 test_travel_tools.py:56 的名单/schema 一致性断言；验证 `replace` 派生的 live/repair 定义仍保留输入类。⑦ 修订证据、测试适配范围和方案后重审，当前不允许直接实施。

## REF-008

- 裁决: APPROVE
- 理由: 过时 docstring 实际位于 scripts/dev.py:112。第 113–119 行按文件是否存在决定拒绝或启动评测；文件缺失时不启动进程已有测试，见 test_dev.py:135 至第 144 行。
- 附加条件: 仅将 docstring 改为“评测入口文件缺失时明确拒绝，不伪造结果。”；守卫、返回码、终端错误文案和测试保持不变。终端文案也含历史措辞，但本次不批准扩大修改。

## 执行顺序建议

1. **第一批：REF-001 + REF-003 + REF-004 + REF-005 + REF-008，可合并同一提交。**这些改动互不依赖，均是删除无消费者声明或校正文档。完成标准：范围准确、测试和 prompt 无改动，运行：
   ```text
   uv run python scripts/dev.py check
   uv run python scripts/dev.py db-up
   uv run python scripts/dev.py test
   uv run python scripts/dev.py web-check
   ```

2. **第二批：REF-002，独立提交，生产删除和必要测试适配同一提交。**便于单独核查费用保护与测试删除依据。完成标准：上述三个旧行为用例之外没有测试删除，所有保留断言及新增三项验证通过；运行：
   ```text
   uv run python -m pytest -q tests/test_protocol_probe.py tests/test_sdk_budget.py tests/test_human_no_daily_cap.py
   uv run python scripts/dev.py check
   uv run python scripts/dev.py db-up
   uv run python scripts/dev.py test
   ```

3. **第三批：REF-006，修订获批后独立提交。**完成标准：全部消费点输出等价，空项、顺序、规范化、兜底和错误顺序保持；运行：
   ```text
   uv run python scripts/dev.py web-check
   ```
   另外提供三个 select 的实际选项/顺序及两种住宿标签、未知口径兜底的前后对比证据；现有测试不足以证明这些 JSX 输出等价。

4. **第四批：REF-007，修订获批后独立提交。**注册表、生产指纹排除和测试复制点适配必须原子提交。除逐项指纹一致外，运行：
   ```text
   uv run python scripts/dev.py check
   uv run python scripts/dev.py db-up
   uv run python -m pytest -q tests/test_mcp_bridge.py tests/test_fencing.py tests/test_trace_log.py tests/test_travel_search.py tests/test_evaluation_variants.py tests/test_eval.py tests/test_eval_metrics.py tests/test_eval_compare.py tests/test_diagnostics.py tests/integration/test_travel_tools.py tests/integration/test_database_eval.py tests/integration/test_evaluation_variants.py
   uv run python scripts/dev.py test
   ```

REF-007 改动前、后分别执行以下命令保存输出，逐行比较 **16 个命名集合**，不能只比较去重后的哈希：

```text
uv run python -c "import json; from typing import get_args; from backend.providers.claude_agent.evaluation import EvaluationVariant, evaluation_definitions; from backend.tools.search import DEFINITIONS as S; from backend.tools.travel import DEFINITIONS as T; from eval.run import schema_fingerprint as F; sets={'search':S,'travel':T}; sets.update({f'{v}/database={db}':evaluation_definitions(v,database=db) for v in get_args(EvaluationVariant.__value__) for db in (False,True)}); print(json.dumps({k:F(d) for k,d in sets.items()},sort_keys=True,indent=2))"
```

提案记录的“四个 SDK capability 基线失败”本次没有运行复证。实施方必须在改动前记录准确测试 node ID 和失败原因，改动后证明完全相同；不得按“允许四个失败”的数量放行，不得新增 skip、改断言或隐去失败。每批交付 diff、验证结果和必要测试适配说明后再验收提交。

本次审批基于 `e29cdda49698bb3da94216c3d49fa94f7535e843`；全程只读，未修改文件，未运行会写缓存或数据库的测试命令。