# 2026-10-19 修复：核心条件已齐却不发合并选择卡（用户卡死）

分支 `batch/2026-10-19-architecture-hardening`，承接 [ask-and-select-flow](2026-10-19-ask-and-select-flow.md)。

## 现象

线上 7da3f2f（DeepSeek，新建多城市会话，与此前成功运行相同的用户消息）：模型调用 `update_travel_request`、`update_conversation_state` 两次，共 4 次模型请求、无报错。助手文字问“是否有同行儿童；如有请提供年龄”，并承诺“请在底部卡片里一次确认…”，但**没有任何卡片**（刷新后也没有）。用户既无处回答卡片，也被文字问题引向另一条路，卡死。此前同一流程卡片正常出现，说明与模型选择的路径有关。

## 假设与排除（有证据）

1. **awaiting_field=child_ages 阻塞发卡**：排除作为直接原因。`ensure_trip_ask_in_transaction` 不读 `awaiting_field`；`update_conversation_state` 虽然保存它，但发卡判断与其无关。
2. **卡需要特定 awaiting_field 或酒店/规划工具尝试**：排除。服务端在 `update_conversation_state` 内每次都调用 `ensure_trip_ask_in_transaction`，另有搜索/规划工具的闸门。
3. **别的会话的 memory_confirm 卡挡住**：排除。查询只限 `session_id` 且 `purpose=trip_ask` 的 form 卡，与 memory_confirm 无关。
4. **“至多一次”标记误设**：排除。`asked` 只统计**已作答**的 trip_ask 卡里的组；未发过卡就为空。
5. **核心条件判定包含 child_ages（成立）**：`backend/services/choices.py` 的 `CORE_FIELDS = (city, start_date, end_date, adults, child_ages, rooms)`，发卡要求其中每一项非 None。该请求用户没说儿童，模型也没写 `child_ages`（None=未知），所以 `all(...)` 为假，直接 `form=None`，既不发卡也不报错。而 `conversation_view.missing_fields` 因 `child_ages` 未知含它，模型据此在文字里追问儿童，并按人设写上“请在卡片里确认”。成功的那几次运行中，模型恰好把 `child_ages` 写成了 `[]`。
   证据：新增集成测试 `test_unknown_children_still_issue_the_card_whatever_awaiting_field_the_model_chose` 复现该路径（清除 child_ages 后记录 goals + awaiting_field=child_ages），修复前断言“有卡”失败的根因即上述 `all(...)`。

## 根因

发卡的前置条件把“儿童年龄”当作必须先由模型写好的核心条件，而它同时又是酒店报价的必填项、会进入 `missing_fields` 引导模型文字追问：两个机制互相错位。模型一旦没写 `child_ages`，就既没有卡、又被引导去文字追问；工具回执也没有明确告诉模型“没发卡”，模型便照人设说“请在卡片里确认”。

## 方案

采用：
- 发卡前置只要城市/日期/人数/房间；`child_ages` 未知不挡发卡，而是卡里多一组「同行儿童」（没有儿童 / 有儿童 + 文字框填年龄，如“5岁、8岁”），排在第一位，每组可不答。
- 答案走同一条服务端校验路径（`trip_ask_patch` → `patch_request_in_transaction(source="user_form")`，即用户明确来源，不绕过 `explicit_fields` 与来源追踪）：“没有儿童”→`child_ages=[]`；文字→解析 0–17 的整数；“有儿童”但不填年龄、文字无法识别年龄、年龄>17、选项与文字同时给，一律 422 拒绝（不猜）。
- 未答（含整卡“确认并继续”而不选）→ `child_ages` 保持未知，**不当作无儿童**：现有语义里 `child_ages` 是酒店报价必填（`hotel_requirements`、`task_missing`），未知本就会阻止报价，我们保持这一行为，不新增默认值。此时因卡已问过一次（`asked`），不会再发卡，模型可在文字里**简短追问一次**（人设已写明）。
- `update_conversation_state` 回执明确：`trip_ask_card` = `issued`（本次新发）/ `pending`（此前已发待答）/ `none`（没有卡），并附服务端文案 `message`（none 时明确禁止声称卡片存在）；卡已含“同行儿童”时清掉模型记录的 `awaiting_field=child_ages`，避免它在文字里再问。
- 人设：不在文字里问儿童/节奏/时间；是否有卡以 `trip_ask_card` 为准，none 时不说“请在卡片确认”。

不采用：
- 把未答儿童默认成“没有儿童”：会把未知写成事实，违背不替用户假设的原则，也与现有必填语义不符。
- 服务端代模型写 `child_ages=[]`：同上。
- 让发卡依赖 `awaiting_field`：模型相关，正是本次 bug 的类型。
- 另加第二种卡专门问儿童：违背“只发一张合并卡”。

## 实现

- `backend/services/choices.py`：`CORE_FIELDS` 去掉 `child_ages`。
- `backend/domain/choices.py`：`TRIP_ASK_SPECS` 增加 `children`（allow_text，text_kind=text）；`trip_ask_form` 在 `child_ages is None` 时出现该组；`trip_ask_patch` 处理 `children`（新增 `child_ages_from_text`）；合并卡组数上限 10→11。
- `backend/services/travel.py`：`update_conversation_state` 回执加 `trip_ask_card`/`message`，清除被卡覆盖的 `awaiting_field=child_ages`。
- `backend/tools/fencing.py`：`trip_ask_card` 加入结构化/枚举键，不被围栏改写。
- `backend/agent/persona.py`：上述人设更新。
- `data/contracts/web-openapi.json`：由 `web-generate` 重新生成（表单组数上限 11）；`api-types.ts` 生成结果不变。
- 前端 `apps/web` 未改：`choice-form.tsx`/`choices.ts` 按卡内 `allow_text`、`options` 通用渲染与校验（与既有“同行”组同形），`children_text` 由 `textKey` 通用生成；生成类型不变（`groups` 上限只在服务端校验）。

## 测试

- `tests/test_trip_ask.py`（新增）：child_ages 未知时出现 `children` 组且排第一、形状正确；已知（含 `()`）不出现；答案“没有儿童”→`()`，“5岁、8岁”→`(5,8)`，未答→保持 None；非法答案（有儿童不填年龄/无法识别/>17/二选一）被拒。
- `tests/integration/test_ask_and_select.py`（新增，真实 PG）：
  - `test_unknown_children_still_issue_the_card_whatever_awaiting_field_the_model_chose`：复现线上路径，卡必发、回执 `issued`、`awaiting_field` 被清；再次记录状态不重复发卡、回执 `pending`；提交文字“5岁、8岁”后 `child_ages=(5,8)` 且不再发卡。
  - `test_state_result_says_no_card_when_nothing_is_left_to_ask`：无可问项时回执 `none` 且文案明确“没有”卡。
- 注：新增测试与实现在同一工作回合内编写，未单独留存“修复前红灯”的运行记录；根因由代码（`CORE_FIELDS` 的 `all(...)`）和测试路径共同确认。

## 改动的既有测试及理由

无既有测试被修改。全量首次运行 2 个失败均由本改动引起且已修正、未改测试：`test_persona`（人设改写时误删了必检短语“不要在文字里问卡片已覆盖的内容”，已恢复）；`test_web_schema`（组数上限变化使契约漂移，已重新生成契约文件）。

## 遗留

- 用户在卡里点“有儿童”但不填年龄会得到 422 提示（前端选项与文字框互斥，无法同时给）；可后续让前端在选中“有儿童”时聚焦文字框。
- 年龄文字仅识别阿拉伯数字（“两岁”“三岁”会被拒，提示重填）。
- 用户整卡不答儿童时，仍需模型文字追问一次（现有必填语义，未改）。
- 其它必需条件（城市/日期/人数/房间）缺失时仍只能在对话里追问，这是设计。
