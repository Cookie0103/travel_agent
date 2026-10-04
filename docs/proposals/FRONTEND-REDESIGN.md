# 前端 Redesign 方案 v2（Chat-first 旅行 Agent）

> 给实现者（Sonnet 等）：本轮只改 `apps/web/src/components/*`、`apps/web/src/app/*`、`globals.css`。
> **不改** `lib/use-workspace.ts`、`lib/api.ts`、`lib/availability.ts`、`lib/api-types.ts`（生成文件）、后端、契约。
> 不新增 npm 依赖（FRONTEND.md：新依赖先写 ADR）。纯 CSS + React。
> 参考实现：`/Users/ke.chen/開発/agent/commerce-agents/examples/travel/storefront-web` 与 `examples/web-shared`（Anthropic 的 commerce-agents）。

## 0. 定位修正（v1 的错误）

v1 把它当成"规划工作台"，保留了「攻略」一级导航、左侧大表单。这是错的。产品定位应当是：

**一个对话式旅行 Agent：用户用自然语言说"想去哪、几天、几个人、预算、偏好"，Agent 在后台查询、比较、排行程、暂留酒店，结果以卡片形式回到对话里；用户确认后保存为"我的行程"。**

因此：
- 主界面 = 对话。不是表单、不是攻略站。
- 品牌不写死城市：产品名用中性名（如「旅程助手 / Tabi Agent」），城市只作为数据出现（`request.city`）。
- Wikivoyage 攻略在本项目里**不只是评测集**：后端的景点/攻略搜索工具用它作为证据来源（REASONED，见 `backend/tools/travel.py`、`/articles` 接口）。所以它不应是一级页面，但应作为**卡片上的"来源"引用**出现——这正是"有依据"的卖点。`/articles` 路由保留可访问，从导航中移除。

## 1. commerce-agents 是怎么做的（已读代码）

| 方面 | commerce-agents travel storefront | 对本项目的启示 |
|---|---|---|
| 外壳 | `StoreShell`：品牌 + 仅两个视图「Assistant / Trips」+ 右侧 Trip 面板（可开关的 sheet） | 我们只要「对话 / 我的行程」两个入口 |
| 结果展示 | **Generative UI**：Agent 的 `ui` 事件按 `component` 映射成卡片（`ItineraryTimeline`、`ComparisonSpread`、`BookingStatusCard`、`PlanChecklist`…），**内嵌在对话流里** | 酒店比较、行程草稿以卡片出现在回复下方，而不是页面底部堆叠 |
| 购物车/行程 | `TripPanel`：右侧面板常驻当前行程与预订，主操作（checkout）在面板里 | 行程草稿确认、暂留预订放在右侧「本次行程」面板 |
| Agent 过程 | 回复下方一行"当前步骤"；顶栏 `ActivityButton` 打开 `Inspector` 抽屉，列出每次工具调用/结果 | 我们已有 SSE `tool_started/finished`，直接复刻 |
| 空状态 | `HomeView` + `Suggestions`：问候 + 几条可点的示例提问 | 替换掉 Hero 和"创建演示会话"页 |
| 假数据 | 全部虚构（ACME），**只在 README 说明一次**；另有 `/showcase` 路由用 fixtures 渲染所有卡片，不需要 API | 免责声明收成一行；离线演示≈showcase 的定位 |
| 真实 LLM | 同一套 UI，只要有 `ANTHROPIC_API_KEY`；没有离线/在线切换 | 我们保留模式切换，但降级为输入框旁的"模型选择" |

## 2. 现实约束（读后端得出，必须如实反映在 UI 上）

| 用户期望 | 后端现状 | 前端本轮能做什么 |
|---|---|---|
| 去日本任何地方 / 京都→神户→大阪 | `backend/domain/catalog.py:26` `city: Literal["京都"]`；`persona.py:31` 明确"只支持京都，其他地区拒绝并询问" | 外壳做成目的地无关；欢迎页标注「当前数据覆盖：京都」。**多城市需要后端改造，本轮不做** |
| 昨天的对话今天还能找到 | 无"列出会话"接口；`GET /sessions/{id}` 只返回 `session_id, created_at`；无消息历史接口；令牌存在 `sessionStorage`（关标签页即丢），24h；`/demo/login` 每次创建新用户 | 只能保证"同一标签页刷新可续接"。会话侧栏按最终形态设计，但历史列表**隐藏**，等后端接口 |
| 在旧行程上继续增删项目 | 已支持：确认后的正式版本 + 稳定 `item_id` 局部修改 + 锁定（同一会话内） | UI 要把"基于 V2 修改，N 项变化"的差异展示做好 |

**需要后端补的（列给后续，不在本轮）**：
- B1 `GET /sessions`（当前用户会话列表：标题、目的地、更新时间、是否有正式行程）
- B2 `GET /sessions/{id}/messages`（用户消息 + 每次 run 的 answer 与 presentation，用于重放对话）
- B3 持久身份（替代每次新建 demo 用户 + `sessionStorage`），否则跨天必然丢
- B4 多城市数据与 `city` 放开、persona 去掉"只支持京都"
- 前端为 B1/B2 预留组件位置，但**不得调用不存在的接口**，也不得用 localStorage 伪造"历史会话"。

## 3. 信息架构与路由

| 路由 | 角色 | 变化 |
|---|---|---|
| `/` | 对话（主界面） | 重写为 chat-first |
| `/?article=<id>` | 从来源引用进入对话 | 保留：引用卡出现在输入框上方，只填文字不发送 |
| `/plans` | 我的行程（已确认版本，只读） | 视觉统一 |
| `/articles`、`/articles/[id]` | 来源资料 | 保留可访问，**从顶栏移除**；从卡片"来源"链接进入；页面标题改为「来源资料」 |

顶栏：`◆ 旅程助手` ｜ `对话` `我的行程` ｜ 右侧：`Agent 活动` 按钮、会话菜单。

## 4. 主界面布局

```
┌────────────────────────────────────────────────────────────────────────────┐
│ ◆ 旅程助手    对话  我的行程                     [⚡ Agent 活动 3]  会话 ▾ │
├───────────────────────────────────────────────────┬────────────────────────┤
│                                                   │ 本次行程          [×] │
│   你：京都三天两夜，2 个大人，预算 5 万日元，      │ 京都 · 11/03–11/05     │
│       想看寺庙，少走路                             │ 2 成人 · 1 间 · ¥50,000 │
│                                                   │ 公共交通 · 09:00 [编辑] │
│   ◆ 正在比较酒店…（search_hotels ✓  compare ●）   │────────────────────────│
│                                                   │ 行程草稿 · 部分可校验   │
│   ◆ 我比较了 3 家同口径报价……                      │ Day 1 11/03            │
│     ┌ 酒店比较卡（内嵌）──────────────────────┐   │  ① 清水寺 09:30–11:00  │
│     │ A ¥32,000 最低  B ¥35,400  C 总价未知    │   │  ② …                  │
│     │ [暂留 A]          来源与版本 ▸           │   │ Day 2 …                │
│     └──────────────────────────────────────────┘   │────────────────────────│
│                                                   │ 预订                    │
│                                                   │  A 已暂留 · 等你确认    │
│  ┌──────────────────────────────────────────────┐ │────────────────────────│
│  │ 说说你的旅行计划…                             │ │ [ 确认保存此版本 ]      │
│  │ 模型：离线演示 ▾        □允许计费     [发送] │ │                        │
│  └──────────────────────────────────────────────┘ │                        │
│   模拟酒店与订单，不会真实付款 · 数据说明          │                        │
└───────────────────────────────────────────────────┴────────────────────────┘
          对话 minmax(0, 760px) 居中                    本次行程面板 380px
```

- 宽屏（≥1200px）：对话 + 右侧「本次行程」面板常驻（可收起）。
- 中屏/窄屏：面板变为右侧 sheet，顶栏出现「本次行程」按钮（有草稿/暂留时带红点）。
- 不再有左侧表单栏。会话侧栏（B1 之后）将来放在最左，可折叠；本轮不渲染。

## 5. 组件设计

### 5.1 对话流 `Conversation`
- 数据只来自现有 hook：本轮发送的文本、`workspace.run`、`workspace.events`、`workspace.hotels/plan/bookings`。
- 用户气泡：组件内 `useState` 记录本标签页已发送的消息列表（`{text, runId}`）。刷新后只能显示最新一次 run（hook 只恢复最新状态）——在会话菜单里如实注明，不伪造历史。
- Agent 回复：`run.answer`，纯文本（`white-space: pre-wrap`），禁止 `dangerouslySetInnerHTML`。
- 进行中：回复位置显示一行当前步骤（最后一个未结束的 `tool_started` 的中文名），无步骤时显示 shimmer。
- **内嵌卡片**：最新一次 run 完成后，在该回复下方渲染与本轮相关的卡片：
  - `workspace.hotels` 存在 → 酒店比较卡（复用 `HotelResults`，紧凑化）。
  - `workspace.plan` 是草稿 → 一张摘要卡「已生成 3 天草稿 · 部分可校验 · 在右侧查看并确认」，点击打开面板（完整行程只在面板里出现一次，避免重复的确认按钮）。
- 失败/取消/partial/unknown：回复气泡改为对应状态样式，绝不显示成成功。`run.status` 中文映射：running 处理中、cancelling 取消中、completed 完成、failed 失败、cancelled 已取消、partial 部分完成、awaiting_user 等你操作；未知值原样显示。
- 运行中，输入框发送按钮变为「■ 停止」（沿用现有 `active` 与 `workspace.cancel`）。
- `aria-live="polite"` 放在消息列表容器；textarea 保留 `sr-only` label 和 `maxLength={4000}`。

### 5.2 空状态 / 欢迎
- 未建会话：居中问候「想去哪里玩？」+ 一句说明 + 主按钮「开始」（调用 `workspace.login`，`disabled={busy || restoring}`；restoring 时文案「正在恢复上次会话…」）。
- 已建会话、无消息：问候 + 3–4 条示例提问 chips（点击填入输入框；离线模式下点击直接触发对应预设）。下面一行小字「当前数据覆盖：京都」。

### 5.3 模型选择（取代原"执行模式"下拉）
- 放在输入框左下角，形似 ChatGPT 的模型选择：`离线演示（免费） / 实时模型（DeepSeek / Claude Agent SDK）`。
- 离线：示例 chips 即三个预设（比较酒店 / 生成行程 / 修改第二天下午），点击发送 `演示：…`；预设需要 `request.revision`，没有时 chips 禁用并提示"先在右侧确认旅行条件"。
- 实时：输入框边框变琥珀色，选择器旁出现紧凑 checkbox「允许本条消息计费」；未勾选时发送禁用，并在旁边写原因。
- 语义不变：切换时 `setLiveConsent(false)`；pending 重试在 live 下需同意。

### 5.4 本次行程面板 `TripPanel`
自上而下：
1. **旅行条件摘要**：城市、日期、人数/儿童、房间、预算、交通、出发时间；「编辑」就地展开现有 `<Conditions>`（`key={request.revision}` 保留）。说明文字：「也可以直接在对话里告诉我」。
2. **行程草稿 / 正式版本**：复用 `PlanResults`，改为按天分组（Asia/Tokyo 日期），顶部状态条（绿=通过当前范围校验 / 黄=partial / 红=conflict），有 `base_version` 时显示「基于 V{n} · N 项变化」并可展开差异；全局序号保持（`aria-label` 依赖）。锁定按钮只对正式版本出现（现状）。
3. **预订**：复用 `Bookings`，状态 chip 化。
4. **底部 sticky 主操作**：草稿存在时「确认保存此版本」（禁用条件原样）。
5. 折叠区「长期偏好」：`PreferencePanel`，`key={identity.user_id}` 保留。

### 5.5 Agent 活动抽屉 `ActivityDrawer`（面试卖点）
- 顶栏按钮，运行时脉动，角标为本次 run 工具调用数。
- 抽屉内：按 `sequence` 排列；用 `tool_call_id` 配对 `tool_started`/`tool_finished`，显示 ✓ / ✗（`code` 非空为失败，显示 code）/ 进行中；`argument_keys` 以 chip 展示（只有键名，不显示值）；`context_compacted` 显示分隔线；`presentation` 显示"已更新卡片"。顶部显示 run 模式（离线/实时）与状态。
- 参考 `commerce-agents/examples/web-shared/Inspector.tsx`（只参考结构，不复制依赖）。

### 5.6 卡片规范
- 每张卡只保留**一个**数据性质标签：「模拟报价」/「历史快照」/「估算」。
- 技术字段（`source_ref`、`request_revision`、`content_version`、报价有效期）收进卡片底部 `<details>来源与版本</details>`；`source_ref` 若可解析为攻略（`sourceHref`），渲染为链接到 `/articles/<id>`。
- **不得折叠的风险信息**：总价/税费未知、报价过期、不可比较原因、超预算、行程 conflict/partial/stale、预订 unknown——保持醒目。
- 金额只格式化后端字符串，不做浮点运算；数字 `tabular-nums`。

### 5.7 提示与错误
- 统一 `Banner`（error/warning/info，`role="alert"`），固定在对话流顶部。现有三类原样迁移：`workspace.error`（读取最新条件与行程 / 重新连接进度）、`pending_message`（重试未获响应的消息）、表单错误。
- 全局免责声明只剩输入框下方一行：「酒店与订单为模拟数据，不会真实付款 · 数据说明」，「数据说明」用 `<details>` 展开 4 行（攻略=Wikivoyage 历史快照；酒店=虚构报价；路线=估算；当前覆盖京都）。
- 会话菜单（`<details>`）：会话创建时间、「本会话仅保存在此标签页，关闭后无法找回（演示限制）」、「新对话」按钮（调用 `workspace.login`，需二次确认因为会丢失当前标签页会话）。

### 5.8 其他页面
- `/plans` 我的行程：同外壳；复用只读 `PlanResults`；空状态「还没有确认的行程」+「去对话」按钮。
- `/articles`：标题「来源资料」，卡片主按钮「基于这篇提问」（`/?article=<encoded id>`，现有逻辑）。

## 6. 视觉规范（`globals.css :root`）

```css
:root {
  --bg: #f7f6f2; --surface: #ffffff; --surface-2: #f1f0ea;
  --ink: #1d2a24; --muted: #6b746e; --line: #e3e4dd;
  --brand: #2f5d47; --brand-weak: #e7efe9;
  --live: #b7791f; --live-weak: #fbf1df;
  --ok: #2f7a4f; --warn: #a86b00; --danger: #b42318;
  --radius: 12px; --radius-sm: 8px;
  --shadow: 0 1px 2px rgb(0 0 0 / .05), 0 6px 16px rgb(0 0 0 / .05);
}
body { font-family: "PingFang SC","Hiragino Sans","Noto Sans SC","Microsoft YaHei",system-ui,sans-serif; font-size: 14px; }
```
- 用户气泡：`--brand-weak` 底，右对齐；Agent 回复：无气泡，左对齐带 ◆ 头像（同 commerce/Claude 的风格）。
- 标题 20/600，区块 15/600，正文 14，辅助 12。`:focus-visible` 2px `--brand` 外框。不做暗色模式。

## 7. 不可破坏的行为（逐条自查）

| 行为 | 现在的代码 |
|---|---|
| live 未同意不能发送；切换模式清空同意 | `workbench.tsx` |
| pending 消息重试复用原文本与模式，live 下需同意 | `pending_message` 按钮 |
| 离线预设需 `request.revision` | 预设按钮 disabled |
| 运行中才可取消 | `active` |
| 攻略引用只填输入框不发送 | `ArticleReference` |
| 暂留：busy/过期/总价未知/revision 不一致 时禁用；最低价只在未过期时标注 | `HotelResults` |
| 确认：busy/stale/conflict/已确认 时禁用；只对草稿出现 | `PlanResults` |
| 锁定只对正式版本 | `PlanResults` |
| 预订 confirm/reconcile 的入口与条件 | `bookings.tsx` |
| `Conditions key=revision`、`PreferencePanel key=user_id` | `workbench.tsx` |
| 用户/模型/攻略文本一律纯文本 | 全局 |
| `/plans` 只读，不从 URL 接受身份 | `saved-trip.tsx` |
| 确认行程只出现一个按钮（面板里），对话卡片不重复放确认 | 新规则 |

## 8. 文件清单

| 文件 | 动作 |
|---|---|
| `app/layout.tsx` | 换为 `<SiteNav/>`；metadata 标题改为中性产品名 |
| `components/site-nav.tsx` | 新增（`usePathname` 激活态；对话 / 我的行程） |
| `components/workbench.tsx` | 改为编排：Banner + `Conversation` + `TripPanel` + `ActivityDrawer`；`mode/liveConsent/text` 状态留在这里 |
| `components/conversation.tsx` | 新增：消息列表、内嵌卡片、欢迎/空状态 |
| `components/composer.tsx` | 新增：输入框、模型选择、计费同意、示例 chips、引用卡 |
| `components/activity-drawer.tsx` | 新增 |
| `components/trip-panel.tsx` | 新增：条件摘要 + 行程 + 预订 + sticky 确认 + 偏好 |
| `components/banner.tsx` | 新增 |
| `components/results.tsx`、`bookings.tsx` | 只改标记/样式；行程按天分组；技术字段进 details；新增紧凑变体 prop（如 `compact`） |
| `components/saved-trip.tsx`、`articles.tsx` | 文案与样式 |
| `components/conditions.tsx`、`preferences.tsx` | 不改逻辑；去掉"京都"字样以外的硬编码说明可保留（city 仍由后端固定） |
| `app/globals.css` | tokens + 新布局；删除无用样式 |

不动：`lib/*`、`tests/*`（必须继续通过）、`next.config.ts`、后端。

## 9. 分阶段（每阶段可单独合并）

- **A**：外壳与导航、chat-first 布局、Composer（模型选择+同意）、TripPanel、Banner、免责声明收敛。← 观感变化最大
- **B**：内嵌卡片、ActivityDrawer、run 状态映射、欢迎/示例 chips。
- **C**：行程按天分组与差异展示、`/plans`、`/articles` 统一、窄屏 sheet 打磨。

## 10. 验收

- `uv run python scripts/dev.py web-check` 通过，贴真实输出。
- 演示栈（`http://127.0.0.1:3100`，启动见 README）浏览器走通：开始 → 面板确认条件 → 离线三条演示（酒店卡内嵌出现、行程出现在面板、改第二天下午出现差异）→ 暂留并确认预订 → 确认保存 → `/plans` 刷新可读 → 从卡片"来源"进入 `/articles/<id>` 再「基于这篇提问」回到对话。
- 失败路径：停掉 API → Banner 出现 → 恢复后按钮可重试。
- 390px 窄屏：面板为 sheet、无横向滚动、键盘可操作。

## 11. 刻意不做

- 不伪造会话历史或跨天续接（需 B1–B3）；不放开城市（需 B4）；不加 UI/图标/动画库；不做暗色模式与地图；不改任何 API 调用和状态机。
