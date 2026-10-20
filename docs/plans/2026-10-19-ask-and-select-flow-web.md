# 2026-10-19 一次问清 + 先选酒店再规划：前端（apps/web）实现

对接 [后端契约](2026-10-19-ask-and-select-flow.md) §3。只改 `apps/web/**`；`api-types.ts` 由后端阶段重新生成，本轮未改。

## 实现了什么

1. **合并选择卡**：沿用通用表单卡（`ChoiceForm`），不另写渲染器。`allow_text` 的组在选项下方多一个单行文本输入（`maxLength=40`、placeholder 取自组、`text_kind=time` 时额外一个 `<input type=time>`）。同一组里**选项与文本二选一**：点选项清文本，输文本清选项。`trip_ask` 卡“确认并继续”始终可点，零答案合法。
2. **提交形状**：`selection.answers`：`{key:[option_id]}`、`{key_text:[文本]}`；回显 `answersSummary` 只列有答案的组（含文本），全空时为“确认出行信息”。已提交的卡用 `groups[*].selected` / `text` 回显。
3. **酒店选择**：每段候选**全部显示**（去掉 `slice(0,3)`），不自动选；单城市与多城市同一 UI（“已选 N/M 段”+“按已选酒店统一规划”）。服务端已记录的选择（聊天/归段确认）按 `GET /sessions/{sid}/hotel-selection` 计入已选（本地点击优先）。
4. **跳过**：服务端 `can_skip` 时（仅最新一轮）显示“先不选酒店，先排行程”，提交 `skip_hotels:true`+`expected_revision`；未答复的跳过随 outbox 持久化，刷新后可重试。
5. **无候选**：诚实提示“这次没有找到可展示的酒店报价”，显示 `comparison.search_url`（仅 https）乐天链接，并提示可在聊天里贴乐天链接或酒店名；同样有跳过按钮。
6. **归段确认卡 `hotel_assign`**：文案取自服务端 `question`；确认/否；“否”展开单行输入“是哪个城市？”（≤40 字）并提交 `{city:[文本]}`；`needs_city` 时按服务端选项给“填写城市”（同样展开输入）/“先不选这家”（dismiss，直接提交）。
7. **条件区节奏来源**：`节奏：X（本次指定）` / `节奏：X（长期偏好）`（已确认、active、long_term 的 pace 记忆，取最新）/ `节奏：标准（默认假设，未指定）`。

## 组件与文件

| 文件 | 改动 |
| --- | --- |
| `src/lib/choices.ts` | `setGroupOption/setGroupText`（二选一）、`textKey`、`TEXT_MAX`；`validAnswers` 支持文本键与 trip_ask 零答案；`cleanAnswers` 去空白文本；`choiceMessage` 增加 hotel_assign 规则；`answersSummary`、`selectionText`、`assignOf` |
| `src/lib/hotel-flow.ts`（新） | `skipHotelsMessage`、`effectiveChoices`、`emptyHotelNotice`、`HotelSelectionView` 类型 |
| `src/lib/hotel-groups.ts` | 去掉每段 3 家截断 |
| `src/lib/pace.ts` | `paceLine`、`longTermPace` |
| `src/lib/api.ts`、`identity-storage.ts` | `MessageSelection` 增加 `skip_hotels`；去重比较与 outbox 恢复 |
| `src/lib/use-hotel-selection.ts`、`use-long-term-pace.ts`（新） | 读 `hotel-selection` 与 `/memory`（与偏好面板同一接口，无新增后端字段） |
| `src/lib/use-workspace.ts` | 暴露 `hotelSelection`；选择卡聊天文本改用 `selectionText` |
| `components/choice-form.tsx`、`choice-card.tsx` | 文本输入；`AssignCard` |
| `components/results.tsx`、`conversation.tsx`、`workbench.tsx` | 空结果提示、跳过按钮、服务端已选计入、类型放宽 |
| `components/trip-panel.tsx` | 节奏来源行 |

## 与后端契约的对应表

| 契约 | Web |
| --- | --- |
| `ChoiceForm.purpose=trip_ask` | `validAnswers` 允许零答案 |
| `FormGroup.allow_text/text_kind/placeholder/text` | `ChoiceGroup` 文本输入 / `type=time` / 回显 |
| `answers.{key}_text`；选项文本同提交 422 | `setGroupOption/Text` 互斥 + `validAnswers` 拒绝并存 |
| `GET /hotel-selection` `state/segments/can_skip` | `useHotelSelection`；`can_skip`→跳过按钮；`segments[].selected`→已选计数 |
| `skip_hotels` + `expected_revision`，不与其他字段并存 | `skipHotelsMessage`；outbox 校验拒绝并存 |
| `comparison.search_url`（空结果） | `emptyHotelNotice` |
| `kind=hotel_assign`、`assign.needs_city`；deny 必须带 `answers.city`，其余不带 | `AssignCard`、`choiceMessage` 校验 |
| 单城市也有 `segments` | `HotelResults` 走同一段选择 UI |

## 测试

- 新增 `tests/ask-flow.test.ts`（先红后绿）：二选一互斥、trip_ask 零答案/文本校验、cleanAnswers、回显、hotel_assign 提交规则、skip 消息与去重、skip outbox 恢复、单城市全部候选、服务端已选计入、空结果提示。
- `tests/pace.test.ts` 增加 `paceLine`、`longTermPace`。
- 改动的既有测试：`segment-hotels.test.ts` 每段候选由 3 改为 4（用户决定“全部显示、不截断”）。
- `web-check`（typecheck/lint+prettier/test/build）与 `dev.py check` 通过。无浏览器验证。

## 没做或有风险

- 未在浏览器里点过；`type=time` 在不支持的浏览器退化为文本框，部分输入（如半填的时间）会让文本清空。
- 长期节奏每次运行状态变化时多一次 `/memory` 请求；读取失败则按“默认假设”显示。
- 记忆合并确认卡由另一个 agent 负责，本次未动 `MemoryChoices`。
- 服务端已选的酒店仅在其证据仍在展示候选里时才计入；聊天选中但不在当前展示的酒店不会在面板里显示。
- 跳过后的草稿 `unknown` 展示沿用现有未知项样式，没有单独文案。
