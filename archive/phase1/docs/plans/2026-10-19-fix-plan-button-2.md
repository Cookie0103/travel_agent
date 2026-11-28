# 2026-10-19 再修：多城市“按已选酒店统一规划”仍灰（前端，第二次）

只改 `apps/web/**`。

## 现象

线上 1ff95f4：京都(11/20–22)+大阪(11/22–23)。大阪经聊天（归段卡确认），京都点“选用此酒店”。计数“已选 2/2 段”，页面上 3 个“按已选酒店统一规划”全部 `disabled=true`，且没有任何原因文字。真实数据 `GET /hotel-selection`：

`{"state":"awaiting","segments":[{"city":"京都","check_in":"2026-11-20","check_out":"2026-11-22","selected":null},{"city":"大阪","check_in":"2026-11-22","check_out":"2026-11-23","selected":{"evidence_id":"f7676c38-8053-4294-a36f-9b84392e59e1","hotel_name":"天然温泉　浪華の湯　ドーミーイン大阪谷町（ドーミーイン・御宿野乃　ホテルズグループ）","source":"assign_confirm"}}],"can_skip":true}`

## 前一次修复为什么没生效

前一次假设“服务端选择必须对应展示卡片”并改成按 evidence_id 取。纯函数层面确实正确，但它的测试夹具是简化的（段日期、卡片字段、名称都不是真实形态），且只测了 `hotelPlanSelection`，没有覆盖按钮的其余禁用条件。

## 根因（诚实说明）

用真实形态（全角空格+括号后缀的名称、同酒店多个报价、`segment` 的 `evidence_ids` 归段、微秒+时区的 `expires_at`、revision）写了测试 `tests/plan-button-real.test.ts`：`hotelPlanSelection` 返回完整的两段 `hotel_stays`，**没有复现“纯函数返回空”**。也核查了全部代码：前端没有任何地方用酒店名做匹配或启用判断（名称只用于展示和提交文本）。因此按钮灰不是名称问题，也不是该纯函数。按钮禁用条件为 `disabled || !selected || !chooseSegments`；纯函数既然给出 selection，剩下的只能是父级 `disabled`（`!hotelLive`、`workspace.busy`、`restoring`、该轮 `run.status` 为 running/cancelling）或本地卡片 revision/过期校验在真实浏览器里与纯函数输入不同。静态阅读无法区分，**真实根因未能确定**，原先的“静默灰”正是难以定位的原因。

本次能确定并修掉的缺陷：
1. 本地卡片过期/revision 不一致时纯函数返回 `{}`，与“缺段”无法区分，永远没有原因。
2. 服务端选择缺 `hotel_name` 也会被判为不可用，违背“启用只看 evidence_id 和段日期”。
3. 按钮因父级禁用时不说明原因。

## 方案与实现

- `src/lib/hotel-flow.ts`：`hotelPlanSelection` 启用与 payload 只依赖 evidence_id 与段日期，名称只进文本（缺名称不再阻断）；各段都有选择但无法提交时返回准确原因：`STALE_REASON`（报价基于旧条件）、`EXPIRED_REASON`（报价过期/有效期无法识别）、`NO_REVISION_REASON`（条件版本未载入）、`RECLICK_REASON`（服务端选择缺 evidence_id）；有段完全没选则仍返回 `{}`。新增 `planBlockedReason`：各段已选齐但按钮不可用时返回“无法生成规划：<原因>”，父级禁用时用既有的 `inactiveReason`（历史轮/正在处理中），无则“页面正在处理上一条消息，请稍候”。
- `src/components/results.tsx`：按钮下显示该原因行（`role=status`）。
- 同一时刻只有一套实时控件、历史轮不可点：沿用 `hotelSelectionLive`（只有最近的酒店轮可能 live，历史轮 `disabled` 且不传服务端视图），未改动。

## 测试

新增 `tests/plan-button-real.test.ts`（真实 JSON 与名称）：混合（大阪服务端 + 京都本地）生成两段 stay，大阪使用 `f7676c38…` 与自己的日期 11/22→11/23；名称不同于任何卡片仍启用；旧 revision/过期/revision 未载入给出准确原因；`planBlockedReason` 仅在选齐时出现。既有 `plan-button.test.ts` 等未改（其断言仍成立：无 evidence 仍给“请再点一次”）。`web-check` 与 `dev.py check` 通过。

## 没在真浏览器验证

没有在真实浏览器复现，根因未被证实。部署后若按钮仍灰，按钮下方现在会显示具体原因（旧条件/过期/处理中/历史轮），请据此反馈；若无任何文字而按钮仍灰，则说明该块 `hotelLive` 为真、无提交原因但仍禁用，需检查 DOM 的 `disabled` 来源。
