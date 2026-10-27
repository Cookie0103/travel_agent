# ADR-030：通用服务端校验表单取代写死的组合卡

状态：accepted（2026-10-15，计划见[速度与表单方案](../plans/2026-10-15-speed-repair-and-form.md)）。取代[ADR-029](029-combined-travel-details.md)的写死组合卡，统一确认、CAS与幂等沿用。

## 决定

卡种`form`：`groups[]`（key、label、kind=choice|times、multi、required、options[{option_id,label}]），用户答完全部必填题后一次提交`answers={key:[option_id]}`。模型用新工具`present_form(expected_revision, groups)`出题；服务端限制至多4题（含服务端追加的时间题为5）、每题至多6个选项、题目标签至多20字、选项标签至多40字。

- `transport`、`pace`两个key永远使用服务端固定选项（创建时替换模型选项并预选已有值）；答案经服务端表映射为类型字段（`transport`）或规范节奏约束（沿用`pace_patch`的别名清理）。
- 其他题的答案只以`"{label}：{选项标签}"`写入硬条件文本，同标签前缀重复追问时替换；不写类型字段（预算、交通、节奏）。
- 已有抵达/离开时间时，含交通或节奏题的表单自动追加服务端`times`题：答案yes/no，no时`times_corrected`逐条更正，条数与展示一致、每条至多200字（ADR-029规则）。时间题不由模型创建。
- 提交校验：未知题/选项、缺必填、单选多答、更正条数不符均整体拒绝，不写消息不改条件。`selection_prompt`以排序键序列化答案，同`client_message_id`换答案仍返回409。
- 单问题卡（pace、预算放宽、记忆确认）保持一键提交的原协议。
- 提交后答案写回卡片`selected`（更正后的时间写回`shown`），刷新可恢复。

## 兼容（仅读取边界）

数据库里`kind='travel_details'`的行及其`details`内容由`card_from_row`转为`form`；旧提交体`selection.details`由`ChoiceSelection`的前置校验转为`answers`。所有"是否有待确认表单"的过滤使用`FORM_ROW_KINDS`同时认新旧kind，否则"确认前不得规划"门禁会失效。不保留旧逻辑分支。升级前已发出的旧提示词（旧`details`序列化）按相同`client_message_id`重放会因提示文字不同而返回409，属于一次性迁移边界。

## 取舍

模型只能决定问什么，不能决定选项含义和写入位置；不新增依赖或迁移。
