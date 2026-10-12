# Codex 审批与验收记录 — Code Slimming (2026-10-11)

> Codex（gpt-6.1-sol）对每轮提案的裁决要点与附加条件；对每批执行结果的验收结论。
> 调用方式：桌面 app 内置 CLI `codex exec --sandbox read-only`，只审不改。

## 审批记录 — 2026-10-11（第一轮，提案 REF-001~008，基于 commit e29cdda）

裁决总览：REF-001 APPROVE、REF-002 APPROVE（附条件）、REF-003 APPROVE、REF-004 APPROVE、
REF-005 APPROVE、REF-006 REVISE、REF-007 REVISE、REF-008 APPROVE。
完整裁决原文另存于 `codex-verdicts-round1.md`（本目录）。

### 关键修正（Codex 以仓库事实纠正提案的两处错误）

1. **REF-006**：`trip-panel.tsx:134-136` 的住宿三元是**双分支兜底**——所有非
   `per_room_night` 值都显示「住宿总额」。直接改 `find()` 查表会在未匹配时返回
   undefined，**改变兜底行为**。前端 API 层只是类型断言无运行时校验（api.ts:171），
   不能凭 TS 类型忽略该差异。
2. **REF-007**：提案声称「tests/ 内已无指纹复制」是**错误的**——
   `tests/integration/test_database_eval.py:89-92` 仍独立计算完整 `asdict(d)` 指纹
   并与 manifest 比对。新增 `input` 字段后生产 `eval/run.py:387` 与该测试**两处**
   都会遇到 JSON 序列化崩溃，必须两处同步处理。

### 附加条件摘要

- REF-001：只删三常量，不扩大范围
- REF-002：①保留 Entry/entries/read_jsonl/append_line/exclusive，只清方法删除造成的
  无用 import 并校正 docstring；②三个废弃用例逐项记录删除理由；损坏账本用例改读
  `entries()` 保留异常匹配与内容不变断言；③两处 fixture 保持原四字段、金额字符串、
  UTF-8、行末换行；④新增 Budget.reserve 损坏旧账本三断言用例（用有效预算确保到达
  旧账本读取）；⑤**不批准顺带删 SETTINGS**（test_protocol_probe.py:19 保留）
- REF-003：完整定义实际是 models.ts:14-**21**（提案行号不准），删完整函数表达式与专属查表
- REF-004：只移除两个 export，保留 RunSteps 导出与全部文案
- REF-005：仅删该选择器项，保留 .tabular/.price/声明块
- REF-008：docstring 实际在 dev.py:112；改为「评测入口文件缺失时明确拒绝，不伪造结果。」；
  守卫、返回码、终端文案、测试全部不动
- REF-006（REVISE，重审条件）：①未匹配时继续取「住宿总额」标签，不引入新空白/未知/异常；
  ②三个空 option 位置文案与其他 option 顺序/值/标签不变；③校验留在原分支：交通保留
  trim()/等价返回/清空，住宿不新增 trim、保留能力检查/清空/错误顺序/文案；④类型收窄用
  匹配项 value；不添加通用枚举框架、不宣称 satisfies 全覆盖；⑤既有测试不删改；补充验证
  只断言既有行为，覆盖非法值/交通空白规范化/住宿口径带空白仍拒绝/未修改/清空路径；
  ⑥修订后重审，当前不允许实施
- REF-007（REVISE，重审条件）：①input 字段加在所有现有字段之后带默认值，16 项全部
  绑定正确输入类，不得漏项后靠过滤缩小注册表；②eval/run.py 序列化前只排除 input，
  保留其他六字段及原排序/JSON 默认参数/编码/SHA-256；③test_database_eval.py:89-92 纳入
  联动适配：仍独立按原六字段计算预期指纹、保留 92 行比较，**不得改成调用被测
  schema_fingerprint 生成期望值**；④改动前后保存 search/travel/每个 variant×两个 database
  取值共 16 个命名集合的指纹，逐项完全一致，禁止更新旧预期接受漂移；⑤保留 DEFINITIONS
  顺序（SCHEMAS 与 DEFINITIONS 顺序本就不同，消费者按键校验）；⑥保留 test_travel_tools.py:56
  一致性断言；验证 replace 派生的 live/repair 定义仍保留输入类；⑦修订后重审

### Codex 执行顺序建议（照此执行）

1. 第一批：REF-001+003+004+005+008 同一提交（互不依赖的删除/文案修正）
2. 第二批：REF-002 独立提交（生产删除与测试适配同一提交）
3. 第三批：REF-006 修订获批后独立提交
4. 第四批：REF-007 修订获批后独立提交

### 基线失败要求（Codex 特别强调）

提案记录的「4 个 SDK capability 基线失败」本次未复证。实施方必须在改动前记录准确的
失败测试 node ID 与失败原因，改动后证明**完全相同**；不得按「允许四个失败」的数量放行，
不得新增 skip、改断言或隐去失败。

## 验收记录

（每批执行 + 验证后填写）