# 2026-10-15 提速、保证交付、局部修复与通用表单

状态：计划已获用户批准（2026-10-15），实施中。论文依据见[调研记录](../proposals/2026-10-15-planning-repair-research.md)。可执行任务卡见 `.cache/claude-review/2026-10-15/`（本地，不入库）。

## 1. 问题与证据

用户反馈：等待久，最后几轮生成行程特别慢，打断后没有行程；上限放宽也没用；换酒店后整套行程都变；行程没有给吃饭留时间。

生产日志（Railway api，2026-10-14 起，约 7 次运行；每条 TRACE 最多列前 5 项，实际更多）。冲突类型：

| 冲突 | 约数 | 能否本地修 |
|---|---|---|
| `opening_hours` | 16 | 能（平移/换天） |
| `route_departure` | 14 | 能（重建路线） |
| `route_unexpected` / `route_scope` / `route_gap` | 7 / 7 / 7 | 能 |
| `repeated_place_warning` | 7 | 需换景点或去掉 |
| `hotel_over_budget_unaccepted` / `known_cost_over_budget` | 7 | 不能（需换酒店或用户决定） |
| `visit_duration` | 3 | 能（夹到范围） |

约 80% 是时间/路线机械问题。

用户失败运行 `0bfceae7`：连续 4 次 `stage_plan_change` 返回 409（无标签，**推断**为 `require_unique_sightseeing`，日志无直接原因），之后第 5 次与校验被 429 `repair_limit` 拒绝，**没有任何草稿被存下**，所以页面为空。
运行 `e4d5047c`：第 5 次尝试撞 `repair_limit`；第 2–4 次暂存了仍有冲突的草稿。

意外发现（未处理，仅记录）：
1. 运行 `b995379b` 22 次校验中 8 次 `evidence_missing`（404，证据过期/无效），与冲突无关。
2. 429 `repair_limit` 属被拦截工具调用，会置 `stopping_error`，整个运行直接结束，连展示草稿的机会都没有（`providers/claude_agent/database_tools.py:141`、`tools/travel.py` ~436-451）。

耗时（运行 ce02f819，67.4 s，17 次模型请求）：模型接口 56 s（约 90%），服务端工具每次 28–90 ms。每次请求约 1.5 s 固定 + 3.3 ms/输出 token；每次完整输出行程 JSON（约 1250 token）≈ 5.5 s。

## 2. 用户决定（2026-10-15）

- 模型可为非 transport/pace 的组提供选项文字，答案只落成约束文本；transport/pace 选项由服务端固定。
- 服务端可自动去掉塞不下的景点，必须在回复里写明。
- DEFAULT 档路线额度 12 → 30；HUMAN 不限。
- 为用餐留时间：早饭 1 小时、午饭 2 小时（约 12:00–14:00）、晚饭 2 小时。不查餐厅，只留时间。
- 换酒店不应重排整条行程：保留景点与顺序，只改受影响的首尾路线与时间。
- 初稿生成后大部分固定，冲突只改冲突部分。

## 3. 设计

### A. 保证交付与局部修复（后端）
1. 景点重复不再拒绝暂存：存冲突草稿并标"未解决"；`confirm` 仍拒绝冲突草稿（`services/plans.py:216-217`）。
2. 执行器记录冲突数最少的 `(提案, 报告)`；达上限或暂存被拒时交出它。
3. `repair_limit` 不再触发 `stopping_error`；文案改为"用最优候选暂存并展示，如实说明剩余冲突"。
4. 局部修复模块（`backend/domain/` 新增一个小文件，复用 `opening_state`、`validate_proposal`、`PlanningService.routes`、`PlanContent.proposal`）。算子由小到大，每步只接受冲突数严格下降且不引入新冲突，总操作数有上限，已访问集合防环：
   清除多余路线/重建过期路线 → 同日平移进营业时段 → 后推受影响项 → 换到相邻有空档的天 → 去掉优先级最低一项（回复里写明）→ 夹停留时长。
   残余冲突才交给模型做一次小补丁（`UpdateItem`/`RemoveItem`），最多 1–2 轮。
5. 换酒店 = 保留景点与顺序的局部操作（`PlanPatch` 仅改酒店，再重建首尾路线并局部修复），前端不再发"请按它重排每天行程"（`apps/web/src/components/conversation.tsx:383`）。
6. 用餐时间：提示词规则 + 校验里一个仅 `unknown` 级别的 `meal_time` 提示（不制造 conflict），修复时最低优先级。
7. DEFAULT 路线额度 12 → 30。
8. **开工第一步先验证**：平移时间后原路线证据是否仍有效；若需重查，修复循环要计入路线额度。

### B. 通用表单（后端）与 C. 前端
- 卡种 `form`：`groups[]`（key、label、multi、required、kind=choice|times、options[{id,label}]）；≤4 组、每组 ≤6 选项、标签长度有上限。
- 答案 `{answers:{key:[option_id]}}`；`selection_prompt` 对键排序保证重放幂等（同 id 不同答案 → 409 沿用现有逻辑）。
- `transport`、`pace` 在创建时强制用服务端选项；其余组答案写 `"{label}：{option_label}"` 到约束文本，重复追问按前缀替换，不碰类型字段。
- 新工具 `present_form(groups)`；自动卡（`awaiting_field=transport/pace`）改为构造表单。
- 前端 `ChoiceGroup`（`options.map` 出按钮）+ `ChoiceForm`（必选组选完才可"确认并继续"一次提交）；时间"是/不是"作为 `times` 组。单问题卡（预算、记忆）保留一键提交。
- 净删：`TravelDetails*`、`travel_details_patch`、`travel-details-card.tsx`（180 行）、`validDetailsAnswer`、`detailsSummary`、提示词里 details 说明。
- 兼容：数据库旧 `travel_details` 卡与旧标签页待发队列中的 `details` 仍可读；至少 4 处按字符串 `"travel_details"` 过滤的位置（`services/choices.py:105,131`、`services/travel.py:203`、`eval/simulator.py:467`，以及 `database_tools.py` 的"确认前不得规划"门禁）必须同时认新旧 kind。
- `eval/simulator.py` 同步改。新增 ADR-030 取代 ADR-029。

## 4. 不做
候选预过滤、按天并行的模型调用、`evidence_missing` 专项、RL/求解器。

## 5. 验收
`dev check` 与全部测试逐文件；真实模型最多 2 次运行，记录请求数、总耗时与是否出草稿，**不预设达到 40–50 s**；本地 commit，不推送。

## 6. 进度
- 2026-10-15：计划、调研记录写入；三轨实施启动（A 后端修复 / B 表单后端 / C 前端）。
