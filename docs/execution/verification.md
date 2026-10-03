# 功能与验收测试矩阵

2026-10-03 用户补充 Goal / Acceptance Criteria 后建立。设计来源仍为 plan/01–06、docs/tasks 与已接受 ADR；仓库目前没有 docs/spec 目录，不因此另造一套需求。
本表映射需求到验证方法与缺口；实时状态、命令结果和提交只在[执行计划](travel-agent.md)维护。
单元/离线SDK/真实SDK本地脚本/真实模型/真实PG/浏览器/人工证据分别标明；M1.8已提交d239cc7；验证和独立审查结果从执行计划读取。

## 产品回归

| 需求 / 范围 | 正常与主要分支 | 边界 / 非法输入 / 预期失败 / 依赖故障 | 跨模块证据入口 | 仍需补充 |
| --- | --- | --- | --- | --- |
| R01 参数与错误 | search、注册工具、结果回填 | 截断参数、未知工具、额外身份、工具异常 | tests/test_mcp_bridge.py；tests/integration/test_travel_tools.py | 持续按新增工具补故障回归 |
| R02 SDK中断续接 | 实际SDK完整轮次分进程resume同一ID | 丢文件/半JSON损坏/条件/CLI版本/轮中修改，业务快照新建；私有归属 | tests/test_runtime_sessions.py；tests/test_sdk_lifecycle.py；tests/integration/test_sdk_recovery.py | 小样本真实模型续接效果与M4持久卷配置 |
| R03 工具与写入顺序 | 读上限1、写互斥、单会话执行 | 并发消息、版本竞争、取消晚成功 | tests/integration/test_runs.py；test_travel_tools.py | M2重启后裁决 |
| R04 条件patch | set/clear/未写保留、无变更不增revision | 日期逆序、空值、未知字段、版本冲突 | tests/test_travel_request.py；tests/integration/test_travel.py | 浏览器条件失效已验证；真实响应丢失待M2 |
| R05 Evidence与卡片 | 服务端引用/来源/有效期 | 伪造、跨用户/会话、过期、旧revision、缺来源 | tests/integration/test_travel.py；test_hotels.py | 已验证持久presentation与浏览器刷新；真实模型质量待评测 |
| R06 行程校验 | 时间/营业/路线/预算、SDK修正反馈 | 闭馆、跨午夜、缺税、未知路线、预算下界、3轮上限 | tests/test_itinerary.py；tests/integration/test_planning.py；test_sdk_planning.py | 真实模型修复效果、页面警告 |
| R07 局部修改 | 稳定item_id、无关项保留、重复地点 | 锁定/不存在项目、旧base、超长合法草稿 | tests/test_plans.py；tests/integration/test_plans.py | 网页差异/锁定端到端已验证；模型改程效果待评测 |
| R08 确认保存 | 用户API确认、不可变正式版本 | 并发/重复确认、过期/硬冲突/旧条件整笔回滚 | tests/integration/test_plans.py；test_sdk_plans.py | 网页确认及HTTP重复操作已验证 |
| R09 预订幂等 | 同client_ref仅一订单、独立用户确认 | 重复/并发确认、服务重建、跨用户、长条件、51条历史后的恢复 | tests/integration/test_supplier.py；test_bookings.py；test_sdk_bookings.py；test_recovery.py | 实际供应商提交前/后kill对账与浏览器已验证 |
| R10 供应商失败 | 正常预订、有界429重试 | 429/500/实际超时/损坏响应/关联错误/非法Retry-After，终态分类 | tests/test_supplier_adapter.py；tests/integration/test_bookings.py；test_supplier.py；test_recovery.py | 单进程恢复已验证；多worker明确不在实现范围 |
| R11 丢响应对账 | 实际HTTP断传输unknown→查询→booked | 查询500、暂时查无保持unknown、过期锁内缺席证明、不重复下单 | tests/integration/test_bookings.py；test_supplier.py；test_recovery.py | 业务进程强制退出后0/1订单核对已验证 |
| R12 恢复与SSE | 启动只读裁决partial/cancelled，SSE补发；patch/stage稳定业务结果 | API/业务子进程真实kill、供应商提交前/后、条件版本/证据过期/默认参数差异、事务回滚 | tests/integration/test_recovery.py；test_api_restart.py；test_sdk_recovery.py；tests/test_operation_keys.py | HTTP/API重启、浏览器断线刷新/原消息重试/只读SSE复连与401入口已验证；未完成SDK轮次安全新建而非透明恢复 |
| R13 上下文 | 当前条件/正式plan指针/近期引用注入、原生自动压缩后SDK续接规划校验 | 长历史有界、旧Evidence、Skill/工具配对、快照读取失败零请求、摘要接口失败不保存完成指针、轮间版本变化 | tests/integration/test_sdk_database.py；test_sdk_context.py；docs/review/M3.md | 实际CLI/PG机制已测；脚本摘要与人工usage触发不能证明真实模型压缩质量 |
| R14 偏好 | 认证用户查看/部分修改/清空、保留墓碑版本 | 两用户、旧版本/竞争、首次空删除、非法字段、攻略不能写入、旧SDK及旧回答隔离 | tests/integration/test_preferences.py；test_sdk_preferences.py；tests/test_checkpoints.py；docs/review/M3.md | PG/实际CLI/浏览器保存刷新清空已验证，独立两P2关闭；真实模型偏好效果仍需评测 |
| R15 注入隔离 | 正常搜索/业务流程 | 恶意攻略不扩权限、无Shell/文件/偏好写入 | tests/test_sdk_guard.py；tests/integration/test_travel_tools.py | 偏好完成后补正常/恶意对照 |
| R16 确认边界 | 模型只暂存，用户独立确认保存/模拟订单 | 模型无下单工具、伪造user_confirmed、越权确认 | tests/integration/test_sdk_plans.py；test_sdk_bookings.py；test_bookings.py | 本地SDK暂留后订单为零与API确认已验证；真实模型恶意对照待M3 |
| R17 失败归因 | 正常Trace与工具span、API提交事件导出 | 写盘故障不影响结果、未知字段名脱敏、partial/awaiting_user状态 | tests/test_tracing.py；tests/integration/test_run_trace.py；docs/evidence/m26-failure-regression-2026-10-03.json | 已有真实scope失败前后证据；M3补5类注入/unknown与其余坏例 |
| R19 对外只读MCP | 官方客户端legacy/auto、四查询与直接handlers同事实/来源 | 鉴权、跨用户、非法/未知工具、空结果、DB/工具故障、Host/Origin/请求大小 | tests/integration/test_mcp_server.py；docs/review/M3.md | 真实TCP/PG及独立复核通过；仅本机演示Bearer，不声称企业OAuth/公网部署 |
| 酒店比较/刷新 | 同入住口径、并列最低、服务端报价 | 缺人数/税费、不匹配、过期、无库存 | tests/test_hotels.py；tests/integration/test_hotels.py；test_sdk_hotels.py | 网页过期与恢复 |
| M1.8工作台 | 条件→比较→草稿→确认→局部改程 | 类型、SSE分块、错误显示、失效确认、锁定拒绝 | 前端类型/lint/build、PG链路、真实浏览器 | 类型/lint/build/6前端测试、PG全链与浏览器正常/失效/锁定/刷新通过；丢响应实际故障待M2 |
| Trace/评测/角色 | 本地OTLP、规则评分/版本、角色草案 | 导出失败、模型费用守卫、规则坏例 | tests/test_tracing.py；test_eval.py；test_persona.py | Langfuse UI、30/60条、多次模型统计、人工校准 |

R18与C档实现按既定plan明确排除；C档仅交付ADR。新增主要功能同时补正常、分支、边界、输入和合理依赖故障，不只增加happy path。

## 交付检查

- Python：dev check（ruff、format、mypy strict、分层、文档地图）、dev test（默认不付费；真实PG必须可用）。
- 前端：生成契约一致性、TypeScript、官方Next ESLint、Prettier、生产build；浏览器宽/窄布局与核心流程操作。
- 跨模块：API→Agent/SDK→工具→真实PG→持久事件→浏览器；模拟供应商与恢复故障不能只mock数据库。
- CI：配置与本地对应检查分别记录；未push/未远端执行不写CI成功。
- 审查：每个增量独立审查，修复重大问题并复核；检查重复规则/接口、过度抽象与失败路径。
- 未满足项保持开放；外部权限、预算不足或人工校准缺失不得包装为全部完成。
