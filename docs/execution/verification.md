# 功能与验收测试矩阵

2026-10-03 用户补充 Goal / Acceptance Criteria 后建立。设计来源仍为 plan/01–06、docs/tasks 与已接受 ADR；仓库目前没有 docs/spec 目录，不因此另造一套需求。
本表映射需求到验证方法与缺口；实时状态、命令结果和提交只在[执行计划](travel-agent.md)维护。
单元/离线SDK/真实SDK本地脚本/真实模型/真实PG/浏览器/人工证据分别标明；当前未提交M1.8已通过326项Python与前端专项，提交/审查结果仍从执行计划读取。

## 产品回归

| 需求 / 范围 | 正常与主要分支 | 边界 / 非法输入 / 预期失败 / 依赖故障 | 跨模块证据入口 | 仍需补充 |
| --- | --- | --- | --- | --- |
| R01 参数与错误 | search、注册工具、结果回填 | 截断参数、未知工具、额外身份、工具异常 | tests/test_mcp_bridge.py；tests/integration/test_travel_tools.py | 新输出事件失败回归 |
| R02 SDK中断续接 | SDK本地会话引用与resume | 不可恢复安全停止、工具配对 | tests/test_runtime_sessions.py；tests/test_sdk_lifecycle.py | M2业务/SDK保存窗口与进程故障 |
| R03 工具与写入顺序 | 读上限1、写互斥、单会话执行 | 并发消息、版本竞争、取消晚成功 | tests/integration/test_runs.py；test_travel_tools.py | M2重启后裁决 |
| R04 条件patch | set/clear/未写保留、无变更不增revision | 日期逆序、空值、未知字段、版本冲突 | tests/test_travel_request.py；tests/integration/test_travel.py | 页面编辑/冲突恢复 |
| R05 Evidence与卡片 | 服务端引用/来源/有效期 | 伪造、跨用户/会话、过期、旧revision、缺来源 | tests/integration/test_travel.py；test_hotels.py | 持久presentation与刷新页面 |
| R06 行程校验 | 时间/营业/路线/预算、SDK修正反馈 | 闭馆、跨午夜、缺税、未知路线、预算下界、3轮上限 | tests/test_itinerary.py；tests/integration/test_planning.py；test_sdk_planning.py | 真实模型修复效果、页面警告 |
| R07 局部修改 | 稳定item_id、无关项保留、重复地点 | 锁定/不存在项目、旧base、超长合法草稿 | tests/test_plans.py；tests/integration/test_plans.py | 网页差异/锁定端到端 |
| R08 确认保存 | 用户API确认、不可变正式版本 | 并发/重复确认、过期/硬冲突/旧条件整笔回滚 | tests/integration/test_plans.py；test_sdk_plans.py | 网页确认与重复操作 |
| R09 预订幂等 | 同client_ref仅一订单 | 重复点击、重启重发、身份隔离 | M2.1–M2.3真实PG/模拟供应商 | 未实现，不能算通过 |
| R10 供应商失败 | 正常预订与有界重试 | 429/500/超时、终态分类 | M2.1–M2.3故障注入 | 未实现 |
| R11 丢响应对账 | unknown→查询→booked | 订单已创建/响应丢失、查询失败、不重复下单 | M2.2/M2.6真实PG与供应商 | 未实现 |
| R12 恢复与SSE | 已提交事件有序只读、取消 | 断线游标、进程退出、DB/SDK非原子窗口、改条件 | tests/integration/test_runs.py；M2.4–M2.6 | 当前仅单进程部分覆盖；真实杀进程/浏览器重连待做 |
| R13 上下文 | 当前条件/正式plan指针/近期引用注入 | 长历史压缩、旧Evidence、Skill与工具配对 | tests/integration/test_sdk_database.py；M3.1 | 压缩故障与长对话完整实验 |
| R14 偏好 | 本人查看/修改/删除 | 跨用户、删除不复活、工具文本不写入 | M3.2 | 未实现 |
| R15 注入隔离 | 正常搜索/业务流程 | 恶意攻略不扩权限、无Shell/文件/偏好写入 | tests/test_sdk_guard.py；tests/integration/test_travel_tools.py | 偏好完成后补正常/恶意对照 |
| R16 确认边界 | 模型只暂存，用户确认保存 | 模型声称确认、越权写入 | tests/integration/test_sdk_plans.py；M2.2 | 下单工具/API拒绝实际证明 |
| R17 失败归因 | 正常Trace与工具span | 5类单根因注入、缺证据unknown | tests/test_tracing.py；M2.6/M3.5 | 完整归因实验与真实修复前后证据 |
| R19 对外只读MCP | 与直接handlers一致 | 鉴权、参数、依赖故障、跨用户 | M3.3 | 未实现；不能用进程内桥接代替 |
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
