# 2026-10-19 一次问清 + 先选酒店再规划（ask-and-select 流程）

承接 [ask-less-flow](2026-10-19-ask-less-flow.md) 第 1–4 轮，**部分撤销其第 2、3 轮**。分支 `batch/2026-10-19-architecture-hardening`。本文是前端（apps/web）实现的契约：后端先落地，前端按本文的 JSON 形状与接口对接。生成类型 `apps/web/src/lib/api-types.ts` 由后端 schema 重新生成，不手改。

## 1. 背景与用户决定

用户（唯一产品负责人，2026-10-19，最终决定）：

1. 同一流程适用于单城市与多城市；单城市就是**只有一个住宿段**。
2. 用户发请求后，如有未定事项，助手**只发一张合并选择卡**（一个表单、多个分组、一次确认），不做多轮追问链，不在文字里问卡片已覆盖的内容。
3. 酒店偏好（住宿类型/是否禁烟/床型）**在搜酒店之前**问（影响搜索）；卡确认后才开始搜。偏好未指定=无要求；用户答“不确定/无要求”绝不阻塞。
4. 搜索后展示**全部候选**（沿用 5–6 个上限，不提高上限与 token）；少则少展示。**永不自动选酒店**；只有用户为**每个住宿段**选定酒店后才规划（复用多城市已有的“按段选酒店”闸门）。超预算候选只显示警告，选中即视为接受。
5. 用户可以在聊天里选：贴乐天链接和/或说酒店名（“我看到乐天这家很好，就住这个”）。链接解析酒店号，用既有 `hotel_id` 搜索路径取报价；只有名字则在**已展示的候选**中归一化匹配，匹配不到就请用户贴乐天链接。保存走与按钮**同一个**服务端校验函数。
6. 多城市里用户没说城市就报了酒店：按酒店所在城市归入住宿段，并弹确认卡“因为你没说，已自动归到{城市}的住宿段，可以吗？”，按钮 确认 / 否；否 → 出现自由文本框问城市，按答案改归段。
7. 一家酒店都没找到：诚实告知、给乐天搜索链接、提供“先不选酒店，先排行程”按钮；有候选时也提供该按钮。流程不死锁。
8. 草稿之后若检测到新增/变更的可长期偏好，发**一张**合并记忆确认卡（默认“记住”）——这是另一个 agent（memory）的任务；本次只保证现有 `memory_confirm` 不被破坏，并留下标记清楚的扩展点（`backend/services/choices.py` 的 `MEMORY_MERGE_EXTENSION_POINT`，见 §3.7）。

沿用前几轮：不重复问交通、不空值回显、选 无要求/不确定 不阻塞搜索、无多余文字追问、超预算不是硬冲突、围栏/去围栏修复、`explicit_fields` 来源守卫（卡片答案是用户明确的；默认值不写成用户事实）。

## 2. 流程图

```
用户请求
  │ 模型：update_travel_request(已说条件) → update_conversation_state(goals)
  ▼
服务端 ensure_trip_ask：核心条件(城市/日期/人数/房间)齐？
  ├─否→ 模型文字追问核心条件(awaiting_field)，不发卡
  └─是→ 计算仍未定的分组(见 3.1 规则)
        ├─为空→ 不发卡，直接搜酒店
        └─非空→ 发【合并选择卡 kind=form, purpose=trip_ask】(每会话至多一张；换版本过期才重发剩余项)
              │ 卡未答期间：search_hotel_offers / estimate_routes / validate / stage 被服务端拒绝
              ▼ 用户“确认并继续”(未答的组=不确定，不阻塞)
         模型 search_hotel_offers(每段) → present_travel_result(全部候选，单城市也带 segments)
              ▼ 停下，等用户选；不估路线、不暂存
   ┌──────────┼───────────────────────────────┐
   ▼          ▼                               ▼
 按钮选酒店   聊天选(链接/名字)               “先不选酒店，先排行程”
 hotel_stays  模型调 select_hotel_from_chat    skip_hotels=true
 (每段)       ├ 单段/文本提到城市→直接记录
              ├ 多城市未说城市→【hotel_assign 卡】确认/否+城市
              ├ 名字对不上候选→提示贴乐天链接
              └ 找不到该店报价→如实告知
   └──────────┴───────────────┬───────────────┘
                              ▼ 每段已选 / 已跳过
              规划(estimate_routes→stage_plan_change→自动展示草稿)
                              ▼
              [扩展点] 合并记忆确认卡(另一 agent)
```

## 3. 卡片与接口契约

### 3.1 合并选择卡（`ChoiceCard.kind="form"`，`form.purpose="trip_ask"`）

沿用既有 `ChoiceCard`/`ChoiceForm`/`FormGroup`；**不新增 kind**（不需迁移）。新增/放宽的字段：

- `ChoiceForm.purpose: "trip_ask" | null`（可选，缺省视为旧表单）。`groups` 上限 5 → 10。
- `FormGroup` 新增可选字段：`allow_text: bool`、`text_kind: "time" | "text"`、`placeholder: string`、`text: string`（提交后回写的自由文本答案）。这些字段为假值/空时**不序列化**（旧表单卡形状不变），所以缺省按 false/null 处理。题目选项仍为 2–6 个。
- 所有分组 `required=false`，`multi=false`。“确认并继续”**始终可点**，一题不答也合法（等同全部不确定，不写任何事实）。
- `any` 选项的标签：`pace`/`lodging`/`smoking`/`bed` 为“无要求/不确定”，`transport` 为“不确定（按公共交通）”，时间类与同行为“不确定”。
- 卡片其余字段不变：`options` 恒为 `[{"option_id":"confirm","label":"确认并继续","value":"confirm"}]`；`question` 恒为 `"请一次确认以下信息，再继续"`。

示例（实际只包含仍未定的组）：

```json
{
  "choice_id": "…", "kind": "form", "session_id": "…", "source_run_id": "…",
  "expected_revision": 5, "stale": false, "answered_option_id": null,
  "question": "请一次确认以下信息，再继续",
  "options": [{"option_id": "confirm", "label": "确认并继续", "value": "confirm"}],
  "form": {
    "purpose": "trip_ask",
    "groups": [
      {"key": "pace", "label": "旅行节奏", "kind": "choice", "multi": false, "required": false,
       "selected": [], "shown": [],
       "options": [{"option_id": "relaxed", "label": "轻松"}, {"option_id": "standard", "label": "标准"},
                   {"option_id": "intensive", "label": "特种兵"}, {"option_id": "any", "label": "无要求/不确定"}]},
      {"key": "wake", "label": "平时几点起床", "kind": "choice", "allow_text": true, "text_kind": "time",
       "placeholder": "如 7:30，或“看情况”", "options": [
         {"option_id": "w0630", "label": "6:30 左右"}, {"option_id": "w0730", "label": "7:30 左右"},
         {"option_id": "w0830", "label": "8:30 左右"}, {"option_id": "w0930", "label": "9:30 左右"},
         {"option_id": "w1030", "label": "10:30 以后"}, {"option_id": "any", "label": "不确定"}]}
    ]
  }
}
```

**分组、顺序与选项**（`option_id`→标签；每组都有 `any`）：

| key | 题目 | 选项 | 写入 request（用户明确） |
| --- | --- | --- | --- |
| `pace` | 旅行节奏 | `relaxed` 轻松 / `standard` 标准 / `intensive` 特种兵 / `any` 无要求/不确定 | hard `节奏：慢节奏/标准/特种兵`；`any` 不写（按标准假设并在条件区显示默认） |
| `wake` | 平时几点起床 | `w0630` 6:30 左右 / `w0730` 7:30 左右 / `w0830` 8:30 左右 / `w0930` 9:30 左右 / `w1030` 10:30 以后 / `any` 不确定；`allow_text`, `text_kind=time` | soft `平时起床：{标签或自由文本}` |
| `evening` | 晚上几点结束 | `e1900` 19:00 左右 / `e2100` 21:00 左右 / `e2200` 22:00 左右 / `e2300` 23:00 以后 / `any` 不确定；`allow_text`, `time` | soft `晚上结束：…` |
| `arrival` | 第一天几点到 | `a0900` 9:00 前 / `a1200` 中午 12:00 左右 / `a1500` 下午 15:00 左右 / `a1800` 傍晚 18:00 左右 / `a2100` 晚上 21:00 左右 / `any` 不确定；`allow_text`, `time` | hard `第一天抵达：…` |
| `departure` | 最后一天几点走 | `d1200` 中午前 / `d1500` 15:00 左右 / `d1800` 18:00 左右 / `d2100` 晚上 21:00 左右 / `any` 不确定；`allow_text`, `time` | hard `最后一天离开：…` |
| `companion` | 这次和谁去 | `solo` 一个人 / `couple` 情侣 / `family` 家人 / `friends` 朋友 / `other` 其他 / `any` 不确定；`allow_text`, `text_kind=text`（“其他”时补充） | soft `同行：…` |
| `lodging` | 住宿类型 | `private` 独立房间 / `dorm` 接受宿舍 / `capsule` 接受舱房 / `any` 无要求/不确定 | hard 规范文本 `住宿：独立房间/接受宿舍/接受舱房/无要求`（`any`=`住宿：无要求`） |
| `smoking` | 是否禁烟 | `nonsmoking` 禁烟 / `any` 无要求/不确定 | `房型：禁烟` / `房型：无要求` |
| `bed` | 床型 | `twin` 双床 / `double` 大床 / `any` 无要求/不确定 | `床型：双床/大床/无要求` |
| `transport` | 交通方式 | `walk` 步行 / `transit` 公共交通 / `taxi` 打车 / `any` 不确定（按公共交通） | 类型字段 `transport`（`any`=`transit`，标签已明示） |

**哪些组会出现**（服务端 `trip_ask_groups`）：
- `pace`/`transport`：request 已有，或**已确认的长期记忆**里有（记忆键 `pace`/`transport`，scope=long_term），则省略；想改的话用户在聊天里说，按本次行程处理。
- `wake`/`evening`：request 已有对应文字，或记忆里有（目前记忆无此键，预留键名 `wake_time`/`evening_end`），则省略。
- `arrival`/`departure`/`companion`/`lodging`/`smoking`/`bed`：**行程专属，每次行程都问**，不看记忆；仅当 request（含用户原话已被模型写入）已有对应值才省略；默认范围“本次行程”，**绝不自动存为长期偏好**。
- 只有酒店比较目标（无行程）时只含 `lodging`/`smoking`/`bed`；行程目标含全部；没有住宿段（当天往返）时不含这三组。
- 每会话至多一张：已答不再发；未答但 revision 变了（过期）则按剩余项重发并取代旧卡。

**时间输入的渲染要求（web）**：对 `allow_text` 的组，在选项下方渲染一个单行文本输入（`maxLength=40`，`placeholder` 用组里给的）。`text_kind="time"` 时可额外提供原生时间选择（`<input type="time">`，值 `HH:MM`）作为输入便利，但提交的仍是字符串；服务端接受任意 1–40 字文本（如 `7:30`、`下午三点`、`看情况`）。同一组里**选项与文本二选一**：用户输入文本时清掉该组选项选择，点选项时清空文本；两者同时提交服务端 422。

**提交**：`POST /sessions/{sid}/messages`，`selection` 形状不变，`answers` 上限放宽到 20 个键：

```json
{"client_message_id": "…", "text": "确认出行信息", "mode": "deepseek", "expected_revision": 5,
 "selection": {"choice_id": "…", "option_id": "confirm",
   "answers": {"pace": ["standard"], "wake": [], "wake_text": ["7:30"],
               "arrival": ["a1500"], "companion": ["couple"], "lodging": ["any"], "transport": ["transit"]}}}
```

- 选项答案键 = 组 `key`，值为 `option_id` 数组（单选 0 或 1 个）；自由文本键 = `{key}_text`，值为 1 个字符串的数组。
- 未出现的键/空数组=未答（等同不确定）。服务端校验：键必须属于卡上的组；`{key}_text` 仅限 `allow_text` 的组；选项必须在该组内。
- 提交后卡片 `form.groups[*].selected` 回写答案，文本答案回写到新字段 `FormGroup.text: string | null`。回显（“确认：…”）只列有答案的组，`any` 显示其标签。

### 3.2 酒店选择状态与跳过

**读取**：`GET /sessions/{sid}/hotel-selection` → `HotelSelectionView`：

```json
{
  "state": "awaiting",
  "segments": [
    {"city": "京都", "check_in": "2026-11-20", "check_out": "2026-11-22",
     "selected": {"evidence_id": "…", "hotel_name": "…", "source": "button"}},
    {"city": "大阪", "check_in": "2026-11-22", "check_out": "2026-11-23", "selected": null}
  ],
  "can_skip": true
}
```

- `state`：`not_applicable`（没有住宿段/条件未齐）｜`awaiting`（尚有段未选且未跳过）｜`complete`（每段已选）｜`skipped`（已选择先不选酒店）。
- `source`：`button` ｜ `chat` ｜ `assign_confirm`。`selected` 只在报价证据仍属该段时出现。
- `can_skip`：`state=="awaiting"` 时为 true。**无论有无候选，酒店面板都应显示“先不选酒店，先排行程”按钮**；没有候选（空酒店展示）时同样显示。
- 单城市现在也带 `segments`（一段）。`present_travel_result(hotel_comparison)` 的结果里 `segments` 对单城市也输出，形状同多城市；web 的按段选择 UI 对单城市复用（选满一段即可提交）。每段展示**全部**候选（后端单城市 ≤6、多城市每段按既有查询上限约 3；web 不要再 `slice(0,3)` 截断已展示的候选）。

**按钮选酒店**：既有 `POST /messages` + `hotel_stays`（每个住宿段一条，单城市一条）+ `expected_revision`，服务端同一校验函数；单城市原来被拒（`request.segments` 为空）现在放行。

**跳过**：`POST /sessions/{sid}/messages`，新字段 `skip_hotels: true`（需 `expected_revision`，不得与 `hotel_stays`/`selection` 同时出现）：

```json
{"client_message_id": "…", "text": "先不选酒店，先排行程", "mode": "deepseek",
 "expected_revision": 5, "skip_hotels": true}
```

效果：服务端记录“本次住宿段集合已跳过”，解除选酒店闸门，助手规划**不带住宿**；草稿里缺少住宿作为 `unknown`（`hotel_missing` / `hotel_stay_skipped`，不是 conflict，可确认）。条件的住宿段变化后跳过自动失效。

**空结果**：`search_hotel_offers` 无候选时，既有空酒店展示（`component:"hotel_comparison"`，`cards:[]`）新增 `comparison.search_url`（乐天旅游首页 `https://travel.rakuten.co.jp/`；深链格式未验证，故只给站点入口）。web 在该展示里显示链接、提示“可把乐天酒店链接贴给我”，并显示跳过按钮。

### 3.3 聊天选酒店（新增服务端工具 `select_hotel_from_chat`）

不是“让模型自己选酒店”：**入参只有 `expected_revision`**，酒店身份完全由服务端从本轮可信用户原话（`task_runs.user_text`，与 `propose_memory` 同源）解析，模型无法提供/伪造酒店。

1. 链接：提取所有 `rakuten.co.jp` 域名 URL（含 URL 编码的联盟跳转参数），取酒店号：查询参数 `f_no`/`f_hotel_no`/`hotel_no`，或路径 `/HOTEL/{no}/`、`/hotelinfo/plan/{no}`。**核实**：`HotelOffer.hotel_id == str(hotelNo)`（`adapters/rakuten.py`），按酒店号的查询（`hotelNo=`）与地点无关，所以链接里的号可直接作 `hotel_id`。注意：仓库里的 21 个乐天原始样本没有 URL，`f_no=` 取自用户说明，仅 `f_hotel_no=` 在样本的图片 URL 中出现过；其余路径格式属“尽力解析”，未离线核实。
2. 只有名字：与会话里已展示（本人、有效、未失效）酒店候选的名称做 NFKC+去空白+大小写/标点归一化比较（最长公共子串 ≥5 字且 ≥ 候选名 60%，必须唯一）；匹配则用该候选自己的报价与段，**不再搜索**；对不上返回 `need_link`，由模型请用户贴乐天链接。不做关键词搜索。
3. 取报价：已在候选里就用候选；否则调既有 `HotelService.search(hotel_id=…, segment_arrive=…)`（单城市省略段）。多城市实时模式先查第一个住宿段，用酒店地址判断所属城市（地址含该段城市），不在该段再查归属段，最多 2 次乐天查询；离线 fixture 逐段试。
4. 归段：单城市只有一段，直接归入；多城市以酒店所在城市归段。用户本轮原话里**提到了该段城市名** → 直接记录；**没说** → 创建 `hotel_assign` 卡（3.4）；城市判不出（0 个或多个段匹配）→ 创建需填城市的 `hotel_assign` 卡。
5. 记录：经与按钮相同的 `validate_stays`（证据归属/新鲜度/段日期/revision 守卫）后写入该段选择。所有住宿段选齐时，同时写入本轮 `selected_hotels`（与按钮路径同一结构），闸门解除，模型继续规划。

返回给模型的 `data`：

```json
{"status": "selected | needs_confirmation | need_link | not_found | search_failed | nothing_to_select",
 "hotel_name": "…", "segment": {"city": "京都", "check_in": "…", "check_out": "…"},
 "remaining_segments": [{"city": "大阪", "check_in": "…", "check_out": "…"}],
 "all_selected": false, "city_mismatch": false,
 "choice": { "…hotel_assign 卡…" }}
```

### 3.4 归段确认卡（新增 `ChoiceCard.kind="hotel_assign"`）

```json
{
  "choice_id": "…", "kind": "hotel_assign", "session_id": "…", "source_run_id": "…",
  "expected_revision": 5, "stale": false, "answered_option_id": null,
  "question": "因为你没说，已自动归到京都的住宿段，可以吗？",
  "options": [{"option_id": "confirm", "label": "确认", "value": "confirm"},
              {"option_id": "deny", "label": "否", "value": "deny"}],
  "assign": {"hotel_name": "…", "city": "京都", "check_in": "2026-11-20", "check_out": "2026-11-22",
             "needs_city": false}
}
```

- 判不出城市时：`assign.city=null, needs_city=true`，`question="没能判断「{酒店名}」属于哪个城市的住宿段，请告诉我是哪个城市"`，`options=[{"option_id":"deny","label":"填写城市"},{"option_id":"dismiss","label":"先不选这家"}]`。
- web：`confirm` → 直接提交；`deny` → 在卡片内展开一个文本输入（≤40 字，“是哪个城市？”）并提交；`dismiss` → 直接提交。
- 提交仍是 `POST /messages` + `selection`：`{"choice_id","option_id":"confirm"}`；`{"choice_id","option_id":"deny","answers":{"city":["大阪"]}}`（`deny` 必须带 `answers.city`，其余选项不得带 `answers`）；`dismiss` 无 answers。
- 服务端：`confirm` 在提交事务里（仅 DB，不调外部）校验证据后记录该段选择，选齐则放行规划；`deny` 保存城市答案，随后那一轮 run 里模型调 `select_hotel_from_chat`，服务端按答案城市匹配住宿段、必要时再查一次该段报价并记录；城市匹配不到任何住宿段，则返回 `needs_confirmation` 并**再发一张** `needs_city` 卡（不静默失败）。`dismiss` 只标记已答。
- 过期：条件 revision 变化后 `stale=true`，提交 409（同其他卡）。

### 3.5 事件

无新增 SSE 事件类型。`select_hotel_from_chat` 返回 `choice` 时，服务端发既有的 `presentation` 事件（`component:"choice"`，字段同 `ChoiceCard` + `assign`）；合并选择卡仍由 `update_conversation_state` 的 `choice` 或闸门返回的 `choice` 发同一 `presentation`。`tool_started/tool_finished` 里新工具名 `select_hotel_from_chat`。

### 3.6 数据校验与不变量（后端保证）

模型不能确认/保存/预订；选择只经服务端校验；围栏、证据/未知语义、`expected_revision`、报价新鲜度守卫不变。`ChoiceSelection.answers` 的键/选项/文本全部由服务端对照卡片校验。

### 3.7 记忆合并卡扩展点

`backend/services/choices.py` 里 `MEMORY_MERGE_EXTENSION_POINT`（常量+注释）标记“草稿暂存之后、合并记忆确认卡生成”的位置；现有 `propose_memory` / `memory_confirm` 逻辑和 `ChoiceSelection.also` 合并提交路径不改。

## 4. 哪些撤销了前几轮的什么

| 前几轮 | 本次 |
| --- | --- |
| 第 2 轮 P-3：单城市“直接用价格最低且最贴近预算的一家酒店并写明”，同一轮 查酒店→展示→规划→暂存 | **撤销**：不自动选酒店；展示后停下等用户选（按钮/聊天/跳过）；persona“宽松流程”段重写 |
| 第 2 轮：单城市不要求先选酒店（闸门只在多城市 `current.segments`） | **撤销**：闸门改按 `trip_segments`，单城市=一个住宿段 |
| 第 1 轮 P-2：酒店偏好“不发卡、不追问”、persona 写“没提就直接查” | **改为**：偏好放进合并卡，**在搜索前**问；仍是可选（`any`/不答=无要求），不阻塞 |
| 第 1 轮 P-1：自动卡只含仍缺的 交通/节奏 | **扩展**为合并卡（含时间/同行/酒店偏好），仍只含**仍未定**的组（B 仍成立，由 `trip_ask_groups` 负责） |
| 第 2 轮：节奏未说不追问不发卡 | **改为**：节奏进合并卡；用户选“无要求/不确定”或不答仍按标准假设，不写成用户事实 |
| 第 2 轮：抵达/离开时间未说视为未知、不问 | **改为**：进合并卡（`arrival`/`departure`）；`不确定`仍视为未知，首末日按全天安排 |
| 第 3、4 轮（超预算只警告、多城市超预算可选） | **保留不变** |

## 5. 数据与迁移

- **迁移 `0024_hotel_assign_choice_kind`**（加法）：把 `choice_cards.kind` 的 CHECK 放宽为 `pace, form, budget_relaxation, memory_confirm, hotel_assign`（`DROP CONSTRAINT` + 新 `ADD CONSTRAINT … NOT VALID` + `VALIDATE`，不改/删数据；降级时不丢数据：把已有 `hotel_assign` 行改成旧代码可读的“已失效”form 卡（`kind=form`、`content.superseded=true`、清空已答选项，原归段信息保留在 `content.retired_assign`），再收紧 CHECK；升级后它们仍是失效卡）。`ChoiceKind` 字面量加 `hotel_assign`，`tests/integration/test_schema_constraints.py` 里的期望随之更新并断言 `hotel_assign` 行可插入、非法值仍被拒。
- **`travel_requests.request_details`**（JSONB，无需迁移）新增 `hotel_flow`：`{"picks": {"{check_in}": {"check_out","evidence_id","source"}}, "skipped": [["{check_in}","{check_out}"], …] | null}`。**不绑 revision**：选择在使用时重新按证据条件和新鲜度校验，住宿段集合变了则失效（`skipped` 与当前住宿段集合比对）。
- `TravelRequest.lodging_skipped: bool`（只读派生，falsy 时不序列化）供校验器把“跳过”降为 `unknown`；它不在 `TravelConditions` 里，不能被 patch 设置。
- 合并卡内容 `content["purpose"]="trip_ask"` 与 `content["form"]["purpose"]`；不新增列。

## 6. 测试计划（先红后绿）

单元（`tests/`）：乐天链接解析；`trip_ask_groups` 的省略规则（request/记忆/酒店目标/无住宿）；`form_patch` 对每组（含自由文本、`any`、冲突提交）的写入；`hotel_assign` 卡模型校验；名字归一化匹配；persona/skills 文本断言；MCP 暴露表含新工具。

集成（真 PG，串行）：合并卡由 `update_conversation_state` 与闸门创建、每会话一张、答完不重发、过期重发；卡未答时 `search_hotel_offers` 被拒、答完放行；单城市闸门（展示后规划被拒，按钮选完放行）；聊天选（链接/名字/不匹配/未找到）；多城市未说城市出确认卡，confirm/deny+城市/dismiss 全路径；跳过后规划放行且草稿可确认（`unknown`）；`hotel-selection` 视图；`skip_hotels` 校验；迁移 0024 与 `test_schema_constraints`；安全：模型无法通过工具入参指定酒店、过期报价被拒、他人会话证据被拒。

全量：`dev check`、串行目标集成测试、`dev test`。

## 7. 风险与未决

- 真模型是否遵守新 persona 未复测（离线约束）；服务端闸门（卡未答拒绝搜索/规划、选酒店前拒绝规划）是兜底。
- 乐天链接路径格式只有 `f_no`（用户说明）与 `f_hotel_no`（样本图片 URL）有依据，其余为尽力解析；深链搜索 URL 未验证，空结果只给站点入口。
- 酒店所在城市靠地址文本包含段城市名判断；地址缺失/别名未覆盖会走“需填城市”卡，不会静默错归。
- 单城市现在必须选酒店才规划；用户既不选也不跳过只能卡在选择步骤——由聊天里的显式提示和跳过按钮负责，服务端不自作主张。
- 多城市每段候选数仍按既有约 3 家（避免提高 token）；用户说的“5–6 个”对单城市成立。
- `select_hotel_from_chat` 里“用户是否真的在选这家”仍由模型判断（服务端只保证酒店身份来自用户原话、经同一校验）；用户随时可用按钮或再次聊天改选。
- 合并记忆确认卡（决定 8）未在此实现。

## 8. 改动的既有测试及理由

见文末“实现记录”。

## 9. 实现记录

### 9.1 后端落点

- 领域：`backend/domain/choices.py`（`trip_ask_form`、`trip_ask_patch`、`AssignInfo`、`hotel_assign` 卡校验、`FormGroup` 文本字段）；`hotel_flow.py`（每段选择/跳过状态）；`rakuten_links.py`（链接取酒店号、名字归一化匹配）；`TravelRequest.lodging_skipped`；`validator.stay_costs` 把“跳过”降为 `unknown`。
- 服务：`ChoiceService.ensure_trip_ask`（合并卡每会话一张、复用/过期重发）、`create_assign_card`；`HotelSelectionService`（`view`、`from_chat`、`answer_assignment`、`write_picks`/`record_picks`）；`validate_hotel_selection` 增加 `partial`，单城市放行；`TravelService.business_context` 的选酒店闸门按 `lodging_segments`（单城市=一段），`complete_conversation_task` 同；`apply_selected_hotels` 单城市也强制已选酒店（`hotel_evidence_id` 或 `hotel_stays`）；`RunService.submit` 新增 `skip_hotels`、按钮路径同样写入 `hotel_flow`。
- 工具与闸门：新工具 `select_hotel_from_chat`（state，入参仅 `expected_revision`）；`DatabaseTools.execute` 对搜索与规划类工具先问 `TravelService.trip_ask`（卡未答则拒绝并按需代发），再查选酒店闸门；`execute_observed` 为新建的卡发 `presentation` 事件；空酒店展示带 `comparison.search_url`。
- 提示词：`persona.py` 第 44/45/55/61/67 段，`skills/hotel-comparison.md`。
- 迁移：`0024_hotel_assign_choice_kind`（仅放宽 CHECK）。
- 契约：`data/contracts/web-openapi.json` 与 `apps/web/src/lib/api-types.ts` 由 `dev.py web-generate` 重新生成（`apps/web` 其他文件未动）。

### 9.2 改动的既有测试及理由（逐条）

1. `tests/integration/test_choices.py::test_cancelling_the_task_retires_its_unanswered_details_card`、`::test_combined_card_stops_automatic_planning_until_explicit_confirmation`：请求夹具里补上合并卡所问的行程信息（`ASKED_HARD/ASKED_SOFT`，文字不含数字以免触发旧的时间确认题）。理由：现在记录 `goals` 后服务端会自动发合并卡，两个测试要验证的是“取消退休显式表单”“显式表单拦自动规划”，不能被新的自动卡抢走断言。断言本身未放松。
2. `tests/integration/test_choices.py::test_awaiting_transport_automatically_emits_card_and_explicit_presentation_reuses_it` → `test_goals_automatically_emit_one_combined_card_and_explicit_form_supersedes_it`：原断言“自动卡（只含交通）被显式 `present_form` 复用同一 choice_id”依赖 ask-less 第 1 轮 B（自动卡=仍缺的交通/节奏）。现自动卡是 `trip_ask` 合并卡；改为断言：自动发 1 张、同状态重复记录不再展示、显式表单取代它（旧卡 `stale`）、revision 不变。
3. `tests/integration/test_sdk_choices.py::test_native_sdk_roundtrips_server_owned_pace_card`：`choices[0]` 由“只含 transport”改为 `purpose=trip_ask` 且组为 `pace, wake, evening, arrival, departure, companion, transport`；第二张显式表单的选项标签断言原样保留。
4. `tests/integration/test_segment_hotel_selection.py::test_initial_planning_waits_for_segment_selection_and_stop_hook_does_not_push_past_it`：同第 1 条补齐已知行程信息（该测试验证的是选酒店闸门）；末尾 `"selected_hotel_stays" not in other` 改为 `other["selected_hotel_stays"] == chosen`。理由：新语义是各段选齐后、尚无正式行程之前，另一轮也沿用同一份已校验选择（否则聊天选齐后下一轮会被要求重选）；正式行程保存后仍只认本轮选择。
5. `tests/integration/test_fencing_tools.py`：评审名单 `PLAIN_OK` 加 `check_in/check_out/evidence_ids`。理由：单城市展示现在也带 `segments`，这三个键的值是 ISO 日期与 UUID，围栏逻辑本来就原样放行（只是评审名单要显式登记）。
6. `tests/integration/test_schema_constraints.py`：`seed()` 对 0024 之前的版本不插 `hotel_assign`；`test_0023_downgrade_…` 期望集合改为“当前集合 − hotel_assign + travel_details”（到 0022 时尚无 hotel_assign）；新增 `test_0024_adds_hotel_assign_and_downgrade_retires_rows_without_losing_them`（含降级后新代码仍能读出失效卡、再升级）。
7. `tests/integration/test_get_routes_are_lock_free.py`：新增 `GET /sessions/{id}/hotel-selection` 到“GET 路由不等会话锁”的参数表。
8. `tests/test_mcp_exposure.py`：登记新工具 `select_hotel_from_chat: state`。
9. `tests/test_persona.py`：`test_unspoken_pace_…` 的断言由“节奏未说明时不追问、不发卡、不写入request”改为“节奏不确定/没答时不写入request，按标准安排”（节奏现在由合并卡询问，原意“不写成用户事实”保留）；`test_prompt_keeps_lenient_one_turn_flow_rules` → `test_prompt_asks_once_then_waits_for_the_user_to_select_hotels`（原断言“同一轮完成”等已被用户决定撤销，改为断言新流程并断言旧自动选酒店文案不再出现）。
10. `tests/test_choices.py::test_auto_card_asks_only_for_fields_still_missing` 与 `domain.choices.groups_for_missing`：自动卡改由 `trip_ask_form` 生成（已按“仍未定”过滤），`groups_for_missing` 没有调用者，连同该测试删除；其意图由 `tests/test_trip_ask.py::test_known_values_are_omitted` 等覆盖。
11. `tests/test_web_schema.py` 无改动，靠重新生成契约通过。

新增测试：`tests/test_rakuten_links.py`、`tests/test_trip_ask.py`、`tests/test_hotel_flow.py`、`tests/integration/test_ask_and_select.py`（见 §6）。

### 9.3 验证

`uv run python scripts/dev.py check`（ruff/mypy --strict/依赖契约/文档地图）通过；`web-check`（类型检查、lint、web 测试、build，apps/web 未改动仅契约重新生成）通过；全量 `uv run python scripts/dev.py test`：2338 passed、1 skipped、0 failed（6 分钟）。离线夹具，无付费模型调用；真模型对新 persona 的遵守情况未复测。
