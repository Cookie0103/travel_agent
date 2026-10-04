# PROJECT_STATUS — 完成审计与冻结结束标准

**最终发布验收：F1/F2 完成，冻结 P0 剩余 0（2026-10-04）。** AC01–AC07 的代码、运行与远端 CI 证据如下；交付记录正常提交/push 后核对当前 HEAD/远端/CI，并立即停止开发。只完成 P0-1/2/3，没有恢复批量评测或新增功能。下文“当前/本次审计”状态为 13:20 的历史审计快照，不能当作仍需实现的任务。

| 最终验收 | 状态 |
| --- | --- |
| AC01 暂留到期与预订回归 | PASS：主代码 17/17 真实 PG，4 个原红分支已通过；独立窄范围审查通过 |
| AC02 全量 Python | PASS：769 passed、2 live deselected，212.63s；无新增跳过 |
| AC03 静态关卡 | PASS：224 文件 win32/linux/darwin strict；ruff/格式、3 条分层契约、10 份文档地图 |
| AC04 前端 | PASS：最终 web-check 类型/lint/格式、14/14 测试、生产 build 全通过 |
| AC05 Demo 与重启 | PASS：六条既有命令均 exit 0；健康启动、三演示、确认/改程/预订幂等、V2/订单 ID/事件重启读取通过 |
| AC06 真实 Agent 证据 | PASS（证据范围）：复用 fa9930b 已有真实规划证据，保持 partial/unknown 限制；本轮 0 新模型请求 |
| AC07 文档/Git/CI | PASS（产品代码）：9db5702481c468f632e2b97c3d4c058bb0ac9239 正常钩子/push/远端 SHA 一致；两次既有 CI 37178553760、37178551128 成功，均覆盖 Python/Web/Docker Demo。交付记录最终提交的 SHA/CI 以当前分支 Git/GitHub 为准，保存后再次核对 |

F1 已应用既有三文件补丁；重复暂留在原锁内持久化一次 expired，GET/确认/业务上下文复用同一判定，confirmed/unknown 不参与到期裁决。现有四分支保留，TypeAdapter 只修测试中的类型表达。首次 check 的一处超长行已用现有 formatter 处理，随后完整 check/test 通过；无架构改动、无新模型请求。

F2 已执行原定 web-check 与 AC05 六命令，均成功。容器保留运行，可打开 http://127.0.0.1:3100。默认免费离线演示；攻略/地点为历史快照，行程校验保持 partial，酒店/订单为模拟。前端/API/供应商/PG 健康，bootstrap 正常退出 0；重启未删卷，未生成新订单。

AC06 对应私有原批次 `.cache/eval/20261004T014804Z-9fb38f8d` 和 [公开测量证据](docs/evidence/m42-controlled-sweep-2026-10-04.json)：二/三日规划各三轮规则通过，来源为 fa9930b。此次只改变 held 时效，不改变 SDK、查询、规划工具或原数据；因此沿用已有证据，绝不声称是最终源码重新跑了全套。历史失败、partial、unknown 和真人 0 继续保留。

产品提交实际时间为 2026-10-04T13:54:29+09:00，push 前重新读取本机日期；分支名的 10-03 仅为创建日期。已有审查与默认测试保留，AGENTS/rules/skills/工作流未修改。最终仅保存交付说明，产品源码仍是上面的已验证版本；不重复本地全量，正常提交钩子继续执行。

**交付后停止，工程 Demo 判定仍为 A。** 354 未执行实验槽位、240 辅助评分、人评及模型质量改善均为公开未完成的 P1/P2，不能标成研究验收完成。演示入口、停止/重启命令见 [README](README.md)；学习与既有演示材料见 [demos](docs/review/demos.md)。

审计时间：2026-10-04 13:20，Asia/Tokyo；UTC 2026-10-04 04:20。审计对象是实际工作区及已提交的 `fa9930beed460ec1f2bfa994045ccd1e53d7d181`，不是尚未应用的私有补丁。

**判断：A. 核心项目已经基本完成，只需要收尾。** 旅行工具、业务状态、前后端、模拟预订、恢复和交付入口均有实现及运行证据。当前不是缺一大批模块，而是有一个未应用的局部修复、未通过的工作区关卡，以及最后一次交付核验。真实模型效果仍有局限，不能说成“所有需求都能可靠完成”。

**冻结结论：剩余 P0 为 3 项，合并成 2 个 milestones。未完成的批量对照、240 次辅助评分和人工校准，均不作为本轮核心项目交付的前置条件，默认停止。** 不新增架构、模块或测试项目。完成下面 AC01–AC07 后结束本轮开发，不因发现“还能更好”继续延长。

这是用户本次要求的交付范围冻结；不修改 AGENTS.md、原设计、安全不变量或历史评测结果。此前完整研究性验收仍有未满足项，不能改成已完成。本文件区分“工程项目交付完成”和“全部研究评测完成”。

## 1. CURRENT STATE

| 已实现的主要模块 | 可工作的范围与证据 | 当前限制 |
| --- | --- | --- |
| 网页 | 工作台、聊天/SSE、酒店卡片、攻略列表与详情、独立正式行程页；实际浏览器确认、刷新和断线恢复已验 | 默认容器演示是脚本驱动；不能冒充真实模型规划 |
| Agent runtime | Claude Agent SDK 0.2.163 / CLI 2.1.114，MCP 工具往返、会话续接、压缩与退出边界；真实 DeepSeek 已运行 | Claude 原生服务实测按用户要求暂缓；无 OpenAI/Gemini 接入 |
| 旅行状态与事实 | TravelRequest、revision、Evidence 归属/来源/失效，真实 PG 事务与用户隔离 | 京都历史快照；缺失数据必须保持 unknown |
| 查询与酒店比较 | 景点/攻略搜索、详情、报价刷新、儿童/房间口径、税费未知及同口径比较 | 酒店为模拟报价；不是实时供应商数据 |
| 行程 | 路线估算、约束校验、最多三轮修复、草稿、稳定 item_id 局部修改、锁和显式确认 | 路线是估算；真实模型的改程与复杂约束效果不稳定 |
| 模拟预订与恢复 | hold → 用户确认 → 下单；幂等、限次重试、unknown 对账、提交前后 kill 与重启恢复 | **到期 hold 重复返回及上下文问题尚未修入主代码**；不做真实付款 |
| Memory / MCP | 显式偏好查看/修改/删除及隔离；对外只读 MCP，真实客户端/TCP 回归 | 无自动偏好写入、向量记忆或多 Agent |
| Trace | 本地 OTel、可选 Langfuse Cloud；真实认证、历史实际 SDK 摘要上传/读回和页面核对已验 | 最新真实 API→SDK→PG→Cloud 同轮联验尚未做，不影响核心旅行 Demo |
| 工程与交付 | 开发命令、迁移/导入、Compose、已有 CI、烟测与三段演示 | 当前演示容器未运行；启动不是“缺功能” |
| 评测设施 | 冻结 20 dev/40 test、真实 PG 初始状态、三轮测量、严格配对、费用与 unknown 报告 | 设施可用 ≠ 模型全部通过 ≠ 人工校准完成 |

### 实际验证状态

- **已提交版本：** 正常提交钩子通过；本次重新查询 GitHub 两次 CI `37169086681`、`37169084562`，均 `completed/success`，HEAD 都是上述完整 SHA。
- **本次工作区前端：** `uv run python scripts/dev.py web-check` 成功；类型、ESLint、Prettier、14/14 测试、Next production build 全通过。
- **本次工作区后端静态：** ruff/lint 和格式通过（224 文件）；`dev check` **失败**，新测试第 307/319 行各有一个 `object` 不可迭代的 mypy 错误；命令在 win32 检查处停止，不能说当前三平台全绿。
- **本次真实 PG 回归：** 暂留到期/缺到期时间的 4 个新分支全部失败，均指向同一处未应用修复。没有删除断言或改成通过。
- **隔离补丁：** `.cache/expiry-fix-20261004.patch` 已有 17 项真实 PG 通过、生产三文件静态检查和独立审查；这是准备完成，**不是主代码已修复**。新测试自身类型问题仍须处理。
- **当前全量 Python：** 本次没有重复跑全量。已提交版本全量关卡通过；当前工作区已证实有 4 个失败，因此不能借旧 CI 声称当前全量通过。
- **运行环境：** 开发 PG17 容器健康，端口 5434。本次 `docker ps` 只有开发 PG，Compose 演示栈未启动。

Git 工作区已有 7 个修改文件及未跟踪的评测证据；本审计另外新增本文件。此前文档修改和 4 个新回归保留，不覆盖；本审计不修改产品代码、不提交、不 push。

## 2. END-TO-END FLOW

DONE 表示实现及对应运行/测试证据存在；PARTIAL 表示链路存在但有缺口；BROKEN 表示有已复现错误；NOT IMPLEMENTED 表示没有实现。它们不是主观完成百分比。

| 从用户需求到结果的步骤 | 状态 | 实际依据/缺口 |
| --- | --- | --- |
| 打开攻略、查看来源、引用到输入框 | DONE | 浏览器/API 已验；引用不会自动发送 |
| 演示登录、创建会话、填写日期/人数/预算 | DONE | 服务端身份及 revision，真实 PG/API 回归 |
| 提交消息、单次 run、展示进度/断线补发 | DONE | 去重、SSE、取消与持久化链路已验 |
| SDK 理解需求、选择注册工具 | DONE（机制）/PARTIAL（效果） | 真实模型可运行，但不保证每次选择正确 |
| 查景点/攻略、获取带来源 Evidence | DONE | 快照查询与真实 SDK 工具往返已有证据 |
| 查酒店、同口径比较、保留未知税费 | DONE | 真实模型酒店正常/未知税/刷新各 3/3 规则通过；业务/页面另有测试 |
| 估算路线、校验、生成可展示草稿 | DONE（业务）/PARTIAL（效果） | 新 full 二/三日规划各 3/3 规则通过；规划候选仍 partial，不能称所有硬约束已确定满足 |
| 用户要求局部修改、保留无关项/锁 | DONE（业务）/PARTIAL（效果） | 纯规则/PG/SDK 回归已有；下午修改真实模型 1/3 通过，偏好改程 1/3 通过 |
| 用户明确确认，保存正式版本，再读取 | DONE | 浏览器/真实 PG 的确认、幂等与只读正式页已验；模型自述不能代确认 |
| 模拟暂留、用户确认、单订单及对账 | DONE（正常/故障主体） | 重复确认、丢响应和进程恢复已有证据 |
| 到期暂留再次被调用或注入上下文 | BROKEN | 仍可显示 held；4 项主库反例失败，P0-1 |
| 重启/刷新后读取已提交状态 | DONE | PG/进程/容器与网页证据；不自动重新调用模型或下单 |
| 真实酒店供应商、付款、公网企业身份 | NOT IMPLEMENTED（范围外） | 原设计是模拟供应商/本机演示，本轮不新增 |

这条链路已经可以做工程 Demo。尚不能承诺任意自然语言请求都成功，也不能展示成实时旅游预订产品。

## 3. BLOCKERS

**没有发现“缺少某个核心模块，导致整个 Demo 无法成立”的代码 blocker。** 唯一即时运行条件是演示栈当前未启动，展示前需运行既有 `stack-up`；Docker/依赖可用是环境条件，不是新增开发。

到期状态缺陷与当前红关卡阻塞正式质量签收，列入下面 P0；它们不意味着正常查询、规划、确认和模拟预订的整条 Demo 链路尚未实现。

不把 Claude key、Langfuse 联验、人评、更多模型、更多评测或更高成功率列为核心 Demo blocker。

## 4. REMAINING P0 — 冻结为 3 项

最终核对：下面三项现已关闭，剩余 0；表格保留冻结时的任务定义与结束条件。

| ID | 必须完成什么 | 明确结束条件 |
| --- | --- | --- |
| P0-1 | 将已经隔离验证的暂留到期修复应用到主代码，处理新回归的类型错误 | 4 个红例变绿；重复操作仍同 ID/仅一次到期历史，无额外 supplier hold/订单；confirmed/unknown 对账不被破坏；不能删测试/降断言 |
| P0-2 | 对最终代码执行既有质量关卡，启动并核对完整 Demo | Python 默认完整测试、三平台 strict/分层/lint/格式、前端测试/构建通过；生成→确认→修改→再确认及重启读取成立 |
| P0-3 | 保存可复现交付：准确状态、运行步骤、正常 commit/push 与既有 CI | 只描述实测范围/限制，工作区所需变更正常保存到当前开发分支；远端 SHA/已有 CI 核对；提交日期正确 |

P0-1 范围为现有 `backend/domain/booking.py`、`backend/services/bookings.py`、`backend/services/travel.py` 和已有 `tests/integration/test_bookings.py`，不另建预订架构。P0-2 不新增一套测试框架。修复 P0 回归产生的直接问题仍属于该 P0，不因此增加新 milestone。

## 5. P1 / P2 — 本轮默认不做

| 事项 | 当前真实情况 | 为什么不挡本轮交付 |
| --- | --- | --- |
| 剩余同源码配置对照 | no_preferences 已执行 6/120；no_repairs、no_compaction 未启动；还欠 **354 个原预定样本槽位** | 是配置实验，不是欠 354 个功能 |
| 全 full 内容/语气辅助评分 | 120 内容 + 120 语气，共 **240 个评分**尚未启动 | 不影响应用执行，机器分也不证明事实正确 |
| 人工抽查与校准 | 真人 0；前 30 回答材料已准备 | 最终学习/研究工作，agent 不能代填真人分 |
| 全量参数/事实语义审阅 | 原 120 回答已整理；385 业务调用中 246 可绑定原参数，139 未绑定；来源绑定不等于正确 | 已保留 unknown；不能用无限审阅拖延工程交付 |
| 最新真实 API→SDK→PG→Cloud 同轮联验 | 准备了私有脚本，未启动；现有 Cloud 与 SDK 独立证据已有 | 属于观测补强，不影响旅行核心流程 |
| Claude/其他模型真实对照 | Claude 用户暂缓；OpenAI/Gemini 未接入 | 不改变当前 SDK 路线，本轮不扩供应商 |
| 继续提升模型成功率、扩充数据、压缩/偏好调优 | 有真实失败；尚无完整效果保证 | 另行确定目标与调用额度；本轮不以“再优化一次”续期 |

此前有限实验实际完成 **5 组 × 120 = 600 个槽位**：full 97 pass/23 failed；B0 18/102；B2 103/17；固定 B1 38 pass/48 failed/34 error；no_skills 101/19。另 no_preferences 已有 6 个通过记录。B1 错误保留，没有重跑原槽位。公开 sweep 证据目前只汇总前四组，第五组以私有原 summary 为准，不把未同步误说成未运行。

这些都是已见 test 的配置测量，不是盲测、事实准确率或显著提升；各组实际观测的压缩事件不能从配置名推断。历史 183 版本和旧实验保留，不强行与新源码配对。

## 6. TECH DEBT — 只记录，不在本轮修复

- 默认数据是京都历史快照，营业时间、费用/路线等有 unknown；酒店、路线及订单部分是模拟/估算。
- 模型规划、改程、遵循偏好和工具参数仍会失败；新 full 97/120 是规则通过率，33 个规划适用记录中 26 候选为 partial、7 无候选，完整硬约束总比率为 null。
- 历史 PG/SDK 间歇失败根因尚未充分证明；最新 CI 通过不抹去原失败。若最终 P0 检查再次复现且挡交付，才作为该次失败诊断，不提前扩展可靠性工程。
- 早期没有在优化前冻结模型质量阈值；不能现在倒填阈值，声称旧实验达标。
- 长执行计划、历史报告与当前恢复点存在冗余/滞后，用户阅读负担较大。本轮仅准确交付入口，不全仓改文档架构。
- 用户暂停后，付费进程已停止、账本未结为 0，但留下旧模型/控制器锁及中断的临时资源。保留原账本/产物；未来恢复前确认无活跃进程后处理本次遗留锁，不清账、不重放批次。本次审计不清理资源。
- `.cache` 有大量运行产物；它们是私有恢复材料，不是需要继续完成的业务目录，不做清理或迁移。

## 7. ACCEPTANCE TESTS — 冻结完成定义

最终签收对象：**本机可运行、可展示、代码与证据可信的京都 Travel Agent 工程项目**。支持既定查询、酒店比较、规划/改程/确认和模拟预订；不是 production-grade 实时旅游平台。

| 条件 | 明确验收内容 | 当前状态/命令 |
| --- | --- | --- |
| AC01 主代码正确 | P0-1 到期/缺期限 4 分支通过；原预订回归不退步，不增加订单 | 当前失败；`uv run --env-file .env python -m pytest tests/integration/test_bookings.py -q` |
| AC02 Python 全量 | 现有默认测试全部通过；包含真实 PG/SDK 本地往返/故障恢复；live 按现有设计排除，不新增 skip | 当前不能签收；`uv run python scripts/dev.py test` |
| AC03 静态关卡 | 三平台 mypy strict、ruff/格式、分层与文档地图通过 | 当前 2 个类型错误；`uv run python scripts/dev.py check` |
| AC04 前端 | 类型、lint/格式、14 个现有测试、production build 全通过 | 本次已通过；`uv run python scripts/dev.py web-check` |
| AC05 完整离线 Demo | 健康启动、查询/比较→草稿→显式保存→局部修改→再保存、模拟预订幂等；重启后状态和有序事件保留 | 历史已验，最终版待核对；见下方 smoke 命令 |
| AC06 真实 Agent 边界 | 有真实 DeepSeek 经 Claude SDK/工具/PG 产生规划草稿的证据；版本、partial/unknown、费用说明准确；模型不能直接确认/下单 | fa9930b 二/三日规划各 3/3 已有证据；引用原版本，不冒充最终版重测。**不要求重跑冻结全套** |
| AC07 交付一致 | README/本报告能说明启动、核心模块、已知限制与测试结果；正常提交/push当前分支，远端 SHA、既有 CI 和日期正确 | 主修复尚未保存，待完成 |

AC06 优先复用已有真实证据。只有最终 P0 改动使这些证据不再覆盖核心行为时，才做**最多 1 个合成旅行需求、单 run ≤12 HTTP**的补验；失败保持失败并诊断，不自动重试或追加整组实验。此次审计 **0 新模型请求**。任何新增付费补验仍须遵守恢复当天实际授权与配置。

AC05 使用已经存在的入口，不另造验收系统：

```text
uv run python scripts/dev.py stack-up
uv run python scripts/dev.py stack-status
uv run python -m scripts.smoke_demo
uv run python scripts/dev.py stack-down
uv run python scripts/dev.py stack-up
uv run python -m scripts.smoke_demo --verify
```

`stack-down` 不删卷。网页 `http://127.0.0.1:3100`；演示 API 8100、供应商 8101、演示 PG 5544；开发 PG 5434。烟测不能替代模型质量证明。攻略→工作台、正式行程页面的浏览器证据见 [页面验证](docs/evidence/m18-pages-2026-10-04.json)，三段既有流程见 [演示入口](docs/review/demos.md)。

### 所有目录的状态、验收与剩余量

下面覆盖全部 Git 跟踪的代码/材料目录及其父目录，再单列本地生成目录。库依赖、缓存与 `__pycache__` 的任意深层子目录按所属生成目录统一覆盖；不把上万个第三方子目录当本项目待开发模块。

| 目录 | 当前程度 | 验收条件 | 本轮还差什么 |
| --- | --- | --- | --- |
| `apps/`、`apps/web/` | DONE | AC04/05 | 最终 Demo 核对 |
| `apps/web/src/`、`src/app/` | DONE：主工作台/路由 | 聊天、卡片、确认及恢复成立 | 无新增页面 |
| `apps/web/src/app/articles/` | DONE：攻略列表 | 读取已导入攻略/来源 | 无 |
| `apps/web/src/app/articles/[articleId]/` | DONE：详情/引用 | 正常、缺失、编码 ID 与显式引用 | 无 |
| `apps/web/src/app/plans/` | DONE：正式行程只读页 | 读取/刷新/错误重试不重复保存 | 无 |
| `apps/web/src/components/` | DONE：展示/交互 | 原人数口径、时效、差异及确认边界 | 无新组件 |
| `apps/web/src/lib/` | DONE：API/SSE/类型/状态 | 同源、消息去重、补发、身份切换 | 无新抽象 |
| `apps/web/tests/` | DONE：14/14 本次通过 | AC04 | 无新增测试 |
| `backend/` | 主体 DONE | AC01–03/05/06 | P0-1 三生产文件 |
| `backend/adapters/` | DONE：HTTP/供应商/Trace 边界 | 原协议/超时/故障测试通过 | 无；Cloud 联验 P1 |
| `backend/agent/` | DONE：应用 runtime 接口/角色 | 原离线/SDK 及角色规则回归 | 真人语气校准 P1 |
| `backend/api/` | DONE：认证/会话/消息/确认/读取 | 原 API/归属/非法输入/故障集成通过 | 无新路由 |
| `backend/domain/` | 主体 DONE | 原条件/Evidence/行程/金额/时区测试 | P0-1 共用到期判定 |
| `backend/mcp/` | DONE：SDK 桥与外部只读服务 | 原客户端/TCP/鉴权与同结果回归 | 无 |
| `backend/persistence/` | DONE：PG 模型/事务/操作键 | 真 PG 并发、回滚、幂等 | 无新表 |
| `backend/persistence/migrations/`、`versions/` | DONE：现有迁移 | 空库可升级，重启不丢业务状态 | 无新迁移 |
| `backend/providers/` | DONE：供应商/runtime 边界 | 默认离线、显式线路、费用/进程保护 | 无新增供应商 |
| `backend/providers/claude_agent/` | DONE：当前正式 runtime | SDK/CLI、工具、guard、resume/压缩回归 | 无重写 runtime |
| `backend/providers/claude_agent/limits.py`、`ledger.py` | DONE：价表/预算配置与费用账本（原 providers/probe 并入） | 保留旧账、本地测试通过 | 无 |
| `backend/services/` | 主体 DONE，过期 hold 有缺陷 | 业务事务/版本/归属与 AC01 | P0-1 bookings/travel |
| `backend/tools/` | DONE：旅行业务工具 | 原 schema/执行/越权/失败回归 | 不新增工具 |
| `backend/tools/skills/` | DONE：两类旅行 Skill | 按需加载及开关机制已有测试 | 完整效果对照 P1 |
| `data/` | DONE：导入入口 | 数据版本/许可/导入一致性 | 不扩数据 |
| `data/contracts/` | DONE：生成 Web schema | 原生成一致性测试通过 | 无手改生成物 |
| `data/fixtures/` | DONE：人工场景数据 | 模拟标识及原测试一致 | 不增加 fixtures |
| `data/snapshots/` | DONE：146 地点+20 攻略 | 版本/hash/许可/来源与未知值保留 | 实时更新范围外 |
| `data/supplements/`、`kyoto-matcha-v1/` | DONE：隔离补充包 | 原默认目录不变、显式导入一致 | 不扩大覆盖 |
| `mock_supplier/` | DONE：报价/暂留/订单/故障 | 正常、429/500/丢响应/幂等 | 不接真实供应商 |
| `eval/` | DONE（设施）/PARTIAL（实验） | 版本/分母/错误/费用/unknown 正确 | 354 槽位+240评分均 P1 |
| `eval/cases/` | DONE：冻结集/历史集 | 原 Case/顺序/期待/hash 不改 | 不加新案例 |
| `eval/calibration/` | DONE（入口）/PARTIAL（人工） | 真实人工配对后才有校准结果 | 人工 P1，本轮不代填 |
| `scripts/` | DONE：开发/栈/烟测/导出 | AC02–05 的现有命令 | 不加新流程脚本 |
| `tests/` | 主体已验，当前关卡红 | AC01–03，原断言保留 | 4 红分支+2类型错误 |
| `tests/integration/` | 主体 DONE，新增到期回归红 | 真 PG/实际 CLI/HTTP/kill | P0-1/最终全量 |
| `tests/live/` | 存在，默认显式排除 | 仅授权 live 才运行，不冒充离线 | 本轮不批量重跑 |
| `docker/` | DONE：后端/前端镜像定义 | AC05 当前代码构建/健康/持久性 | 最终重建核对 |
| `.github/`、`.github/workflows/` | DONE：现有三类 CI | 最终提交的 Python/Web/Demo 全绿 | 不扩 CI/CD |
| `docs/` | 已有完整导航/大量历史材料 | 准确区分主实现、实验和缺口 | P0-3 集中交付说明 |
| `docs/adr/` | DONE：既定设计取舍 | 与当前 SDK/业务边界一致 | 不新增架构 ADR |
| `docs/blocked/` | 历史阻塞说明 | 不把已解/暂缓项当当前 blocker | 不因此追加工作 |
| `docs/evidence/` | 已有脱敏证据，汇总有滞后 | 对应真实版本/命令，不虚报 | P0-3 最终结果同步 |
| `docs/execution/` | 有执行/验收状态；开发已暂停 | 恢复不重放；本文件冻结 P0 优先 | 仅记最终结果，不改 rules |
| `docs/operations/` | 已有过程/失败日志 | 保留原操作/费用/失败 | 无新增报告体系 |
| `docs/review/`、`batch/` | 有独立审查/导学/演示/简历材料 | 描述可核验贡献及局限 | 无新课程/包装工程 |
| `docs/tasks/` | M0–M4 规格已存在 | 保留原要求及历史未验项 | 不以研究待办扩本轮 P0 |
| `plan/`、`plan/实操计划/` | 既有设计来源 | 不擅自重写设计或 C 档边界 | 无新增产品设计 |
| `vendor/` 及全部子目录 | 只读参考，不是项目实现 | 不复制内部原文/密钥进入 Git | 无开发/验收任务 |
| `.cache/` 及全部子目录 | 私有运行/账本/恢复/补丁/临时环境 | 保留原结果和账本、不重复计费 | 暂停资源记录；不清理历史 |
| `.venv/` 及全部子目录 | 本地依赖环境 | uv.lock 可复现；不提交环境 | 无业务任务 |
| `.git/` 及全部子目录 | 版本历史/正常 hook | AC07，不改 main/历史/强推 | 正常保存最终增量 |
| `.mypy_cache/`、`.ruff_cache/`、`.pytest_cache/`、`.import_linter_cache/` | 工具缓存 | 可被对应检查复用/生成 | 无开发任务 |
| `apps/web/node_modules/`、`.next/`、任意 `__pycache__/` | 第三方依赖/生成缓存 | 对应构建/测试通过；不进提交 | 无业务验收任务 |

根目录 `.env` 是秘密配置，不能提交；`.pre-commit-config.yaml`、pyproject、lock、Compose、AGENTS/ARCHITECTURE/README 是工程配置/入口文件，不能按“报告”随意挪进 docs。本审计不移动或删除任何内容。

## 8. RECOMMENDED FINAL PLAN — 仅 2 个 milestones

### F1：关闭已证实到期缺陷与当前红关卡

- 只处理 P0-1：应用已有三文件补丁、修正新测试的类型表达；保持身份/版本/幂等/对账不变量。
- 独立只读复核明确 diff，发现直接相关问题则修复，不泛化重构。
- 验证：

```text
uv run --env-file .env python -m pytest tests/integration/test_bookings.py -q
uv run python scripts/dev.py check
uv run python scripts/dev.py test
```

全部通过后正常提交/push当前开发分支。若失败，只诊断该失败，不靠跳过或改断言过关。本 milestone 不启动真实模型评测。

### F2：最终 Demo、交付证据与保存

- 完成 P0-2/P0-3；复用现有页面和烟测完成 AC04–07，不实现 P1/P2。
- 验证：`uv run python scripts/dev.py web-check`，以及 AC05 六条栈/烟测命令。
- 核对查询/比较、草稿确认、局部改程、模拟预订与重启结果；复用已有浏览器/真实模型证据并说明版本，只有 AC06 的条件成立才做至多一次受限补验。
- 更新本文件验收表及现有交付入口；正常保存/push后核对该提交的既有 CI 与远端 SHA。最终修复没有再改变源码时，不反复跑已通过全量检查；正常提交钩子仍执行。

提交前检查：

```text
Get-Date -Format 'yyyy-MM-dd HH:mm:ss K'
git log -1 --format='%h %aI %cI %s'
git status --short
```

现分支 `batch/2026-10-03-travel-autonomous` 的日期是**创建日期**，不是提交日期。最近六个实际提交均是 2026-10-04；最新为 10:43:38+09:00。本轮不每天新建/改名分支，不改历史时间；后续保存核对当天真实日期。

**最终停止条件：AC01–AC07 有真实证据且满足后，交付并停止开发。** P1/P2、技术债、未做完的研究实验继续公开列为未完成；不把整份历史研究验收标完成，也不因为这些条目继续消耗额度。需要重新开展它们时，另由用户选择具体目标。

审计暂停记录保存在 `.cache/completion-audit-pause-20261004.json`：付费评测已停，no_preferences 原 6 条保留；未结费用 0、旧锁保留，不自动恢复扫组。账本累计 3287 HTTP/75.597392 CNY 保守上界，当日 62.924332 CNY，**均非供应商实际账单**；审计及最终发布均未新增模型调用。用户随后仅恢复 F1/F2 最终发布，不恢复研究批次。

## 2026-10-04 V2 原型变更（追加记录）

本地V2核心已实现：Google真实景点/路线、乐天酒店、Open-Meteo、DeepSeek经Claude Agent SDK、PG与前端结果展示，草稿确认、ICS和30天身份恢复。大阪已完整前端真实验收并重启读回；札幌、那霸、箱根实际完成草稿，部分酒店工具失败合理降级，独立那霸酒店探针成功。天气3小时共享PG缓存、乐天动态上限、手动探针/冒烟和合成结构样本已补齐；个人Google Calendar导入6/6成功。

Google只保存允许ID/30天坐标，详情按需查询，用户已批准替代原七天缓存。真实次数/模型上界、失败边界、检查与剩余范围统一看[执行计划](docs/execution/travel-agent.md)及[V2验收记录](docs/operations/product-v2.md)。Railway V2发布、Claude与V2同轮Cloud实测未进行；本记录不覆盖上方历史交付/研究结论。
