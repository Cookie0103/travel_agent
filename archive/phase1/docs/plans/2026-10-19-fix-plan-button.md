# 2026-10-19 修复：服务端已记录的酒店选择不让“按已选酒店统一规划”可用（前端）

只改 `apps/web/**`。

## 现象

线上（5a6ba9f）多城市京都+大阪：大阪通过聊天选定（服务端已记录、归段卡片已确认），京都点“选用此酒店”。计数显示“已选 2/2 段”，但“按已选酒店统一规划”仍是灰色，点击无反应。再点大阪卡片自己的“选用此酒店”后按钮才可用。

## 根因

计数（`selectionProgress`）合并了服务端与本地选择，而按钮的可用性与提交内容来自 `segmentHotelSelection(rows, effectiveChoices(...))`，它要求每段的选中项必须是当前展示卡片，并用该卡片的 `request_revision`/`expires_at` 校验。服务端记录的选择若不对应一张通过该校验的当前卡片，这一段就被判为未选，按钮禁用；本地点击会把它变成本地卡片选择，于是启用。即“显示计数”和“能否提交”用了两套规则。

## 方案

提交与启用统一走“合并选择”：每段先看本地点击（本地优先，仍校验卡片 revision/过期），否则用服务端 `selected.evidence_id`，段落日期取该段自身 `check_in/check_out`，名称用于提示文本。后端会校验 `hotel_stays` 的 evidence，所以服务端选择不再在前端按展示卡片二次校验。某段服务端选择缺 `evidence_id` 或名称，无法构造合法 stay，则按钮保持禁用并显示“请再点一次该酒店的“选用此酒店””。任何一段既无本地也无服务端选择，按钮禁用（不提示）。“先不选酒店，先排行程”不变。

## 实现

- `src/lib/hotel-flow.ts`：新增 `hotelPlanSelection(rows, local, view, revision, now)` 返回 `{selection?, reason?}`，并导出 `RECLICK_REASON`；payload 形状 `{expected_revision, hotel_stays:[{check_in, check_out, hotel_evidence_id}], text}` 与本地路径一致，文本模板与 `segmentHotelSelection` 相同。
- `src/components/results.tsx`：`SegmentHotelResults` 用 `hotelPlanSelection` 决定按钮可用与点击提交，并在有 `reason` 且控件可用时在按钮下显示原因。高亮仍用 `effectiveChoices`。

## 测试

新增 `tests/plan-button.test.ts`（先写后实现）：仅服务端选择、仅本地选择、混合（大阪聊天+京都点击）均可用且 payload 含全部段；同段本地覆盖服务端；服务端选择不在展示候选中仍可构造 stay；缺段禁用；服务端选择无 evidence 时给出重点提示；本地卡片 revision 过期被拒。`web-check`（typecheck、lint、test、build）通过。

## 没在真浏览器验证

仅有纯逻辑单测与构建检查，没有在真实浏览器和线上后端复现/验证。服务端选择的 evidence 是否被后端接受（过期、revision）由后端校验决定，前端未再预检，若后端拒绝会以既有错误提示呈现。`scripts/dev.py check` 的 ruff 通过，但 mypy 因另一 agent 正在编写的 `tests/integration/test_transport_long_term.py` 报错，与本改动无关。
