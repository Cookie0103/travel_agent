# 2026-10-19 加固收尾与真模型验证记录

承接 [2026-10-18 完整性加固](2026-10-18-completeness-hardening.md)。本文按“做了什么 / 为什么 / 怎么做的 / 看到了什么 / 还剩什么”记录 10-19 的全部工作，目的是以后不必再重复提问。分支 `batch/2026-10-19-architecture-hardening`（已 push；Railway 已切到该分支）。追问流程的修复见 [2026-10-19-ask-less-flow](2026-10-19-ask-less-flow.md)。

## 1. 用户的产品立场（决定了很多取舍）

- 本项目只有用户本人测试使用：D1（live 额度被刷光）、D2（数据保留/删除）**暂缓**。
- 小缺陷、严格校验“放宽”：日期怎么拍、币种检不检查、酒店超预算、标识符豁免偏宽等**都不重要**；只要能正常用、功能齐全。币种一律按日元。
- 酒店搜索/报价要宽松：给出几家大致符合的就行，别为“条件变化/已过期”反复打扰用户（已存记忆 feedback-hotel-flow-lenient）。
- 日期规则：必须是今天（东京）及之后，过去日期报错，上限今天+3 年；其余日期判定不追求精细。
- 设计逻辑的改动先问用户；已授权的清单见下。

## 2. 今天做的事（按时间）

| 事项 | 怎么做 | 结果/证据 |
| --- | --- | --- |
| 复核 R1–R6 | 只读对抗性复核 subagent | R3 限流器 `IndexError`（`rate_limit.py`）、R5 URL 不可见字符、R4 金额子句逗号三个确认的 bug；其余按用户立场不修 |
| 修 3 个 bug | R3：`hit` 淘汰循环把空队列当过期；R5：URL 豁免加 `value.isascii()`；R4：只去千分位逗号 `(?<=\d),(?=\d{3}(?!\d))` | 各有红→绿回归测试 |
| 日期规则 | `check_limits` 下限改为今天，删 `EARLIEST_DATE`；夹具测试用 `fixed_today`（`tests/integration/conftest.py`）钉住时钟 | 5 个依赖 2026-10-11 的集成测试靠夹具通过 |
| R1 真并发 | `tests/integration/test_booking_concurrency.py`（4 个，各 25 轮，真 PG） | 同日期不同酒店恰 1 个 held；变异验证（关掉重叠复查）能变红；**未发现 bug** |
| R2 免锁读路径 | `tests/integration/test_lock_free_read_callers.py`（7 个，在读与写之间注入并发写） | 所有读后写的调用方都会重新加锁并校验 revision；**未发现 bug** |
| 发现的缺口（决定不修） | `hotel_offer` 证据条件不含 `hard_constraints`/`lodging_budget` | 旧报价会被受理，最终 `expired`，不会 `held`；用户决定不加 `require_revision`（会增加提示）。测试固定现状 |
| R6 浏览器复验 | 真 Chrome（离线栈） | 跳到主内容、导航高亮、日元格式、自动滚动已验；修 2 个新 bug（滚动跟随被误判、历史卡按钮缺原因）+ 4 个小问题 |
| 金额格式 | `moneyLabel` 改成 `30,000 JPY`（不用 `JP¥`）；住宿预算区间 `moneyRangeLabel` | web-check 通过 |
| 用户可见文本 | 离线回复里去掉 `<untrusted_text>` 围栏标签（`unfence()`，只在用户可见边界，不动模型侧）；缺交通方式的提示改中文 | `tests/test_user_facing_text.py` |
| 清理第二批 | 删 `UNCAPPED_CNY_DAY`、`Ledger` 3 个写方法；21 个 Rakuten 样本 json 移到 `docs/evidence/rakuten-raw/`；两个一次性探针归档到 `docs/archive/scripts/` | 净减约 35,100 行（其中约 34,300 行是搬走的 json） |
| 依赖 | 删 `anthropic`；显式声明 `mcp`、`starlette`、`httpx2`（dev） | `uv.lock` 少 `anthropic`、`docstring-parser`、`jiter` |
| 迁移 0023 | 旧 `travel_details` 卡改 `form` 并收紧 CHECK；删 `FORM_ROW_KINDS`/`legacy_form`/`legacy_details` | 开发库已迁到 0023（迁移前在副本演练、做了 pg_dump 备份）；开发库 `choice_cards` 为 0 行 |
| 开发库迁移 | 0012→0022（副本演练 0 违规）→0023 | `travel_agent` 现为 0023 |
| `test_live_lock` 偶发 | Windows 上被杀进程的 `msvcrt.locking` 在 `wait()` 后 0.2–1.9 ms 才释放；测试改为 5 ms 间隔重试至 5 s | 重复 25 次通过 |
| 5 个旧失败 | 根因：本机 CLI 2.1.303 不在白名单，且给 Haiku 5.5 发 `thinking=adaptive`，`request.py:136` 只放行 `disabled`。用 `TRAVEL_CLAUDE_CLI` 指到 `.cache/cli-2.1.294/claude.exe`（不进 Git），`dev.py` 只从 `.env` 读这一个键 | 15 个相关测试全绿；pre-commit 钩子不再需要 `--no-verify` |
| CI | 第一次 push 后 CI 红：新测试 `test_environment_configures_and_caps_limits` 没带数据库配置（本机靠 `.env`，CI 没有） | 补假 `POSTGRES_PASSWORD` 后 CI 全绿（教训：以 CI 为准，不只看本机） |
| 文档清理 | 删 `PROJECT_STATUS.md`（2026-10-04 旧快照）、`M0.md`/`protocol-agent-sdk.md` 中已不存在文件的引用 | `dev check` 通过 |
| 演示令牌有效期 | 文档写 24 小时，代码实际默认 30 天（`DEMO_TOKEN_DAYS` 1–365）；保持 30 天，改文档（README、`backend/api/README.md`、ADR-006），公网部署再设为 1 | D8 已决 |
| D 系列待决项 | D4/D6/D7/D9–D15 “按推荐”（多数是保持现状）；D6 仅改界面文案；D15 已做 | 见批次计划 §2 |

## 3. Railway 与真模型验证

- 三个服务（api / web / supplier）的部署分支从 `batch/2026-10-15/latency-optimization` 切到 `batch/2026-10-19-architecture-hardening`（`connect-service-source`），构建与健康检查成功。线上 CLI 为 2.1.286，在白名单内，没有本机的版本漂移问题。
- 真模型（DeepSeek，API 计费）一轮：京都 11/20–11/21、2 成人 1 间房、住宿每晚 1–2 万日元、公共交通、寺庙与抹茶；手动点了 3 次“确认并继续”。
- 结果：条件提取正确并标注来源；乐天实时酒店报价（金额显示 `29,160 JPY`）；生成 2 天草稿（“部分可校验”）。最后一轮 9 次模型请求全部 200，无拦截无报错，输入 token 很小（17,483 / 3,673 / 738 / …）。
- 看到的体验问题（用户确认要修）：①交通方式明明说了，卡片仍问且确认回显为空；②酒店偏好分第二轮才问，用户要点两次确认才出酒店（见 ask-less-flow）；③酒店全部超预算（+45.8%、+58%），用户说**不重要**，不处理。

## 4. 没做 / 不做（及原因）

- 去掉 `users.preferences`、`source_turn_id` 列、删 `ExternalApiUsageRow`/`GoogleCoordinateRow`：收益几乎为零，且需要 DROP COLUMN / 迁移；`test_upgrade_head_matches_models` 会因删类报 `remove_table`，而对应表仍被原生 SQL 使用。
- 最外层 `data` key 的 `untrusted_key_N` 改写：该层 key 是我们工具代码写死的字段名，不是外部文字；风险低，不改。
- 真实模型下围栏、`explicit_fields` 核对是否多拒：只验了上面一轮，未做大样本。
- 评测与研究（354 个槽位、人评、Claude 原生对照）：用户自己做，前提是先把 travel agent 做成熟。
- 偶发测试：`test_choices` 在完整运行里出现过一次失败，单独跑 3 次都过，重提交通过，原因未查。

## 5. 恢复现场所需信息

- 开发库 `travel_agent`：0023；迁移前备份在会话临时目录（`travel_agent_pre_0022.sql`，约 1MB，可能已被系统清理）。
- 本机固定 CLI：`.cache/cli-2.1.294/claude.exe`，`.env` 里 `TRAVEL_CLAUDE_CLI` 指向它；换机器/清 `.cache` 后需重新安装 2.1.294，否则 5 个依赖 CLI 的测试变红。
- GitHub PR #9 对应本分支；未合并 main。

- 节奏默认假设展示：[2026-10-19-ask-less-flow-pace-display.md](2026-10-19-ask-less-flow-pace-display.md)

## 6. 真模型复测记录（单城市，同一需求，线上 api/web）

| 轮次 | 部署提交 | 结果 | 看到的问题 |
| --- | --- | --- | --- |
| 1 | `c2f0e17`（切分支后首次） | 条件提取正确；需点两次“确认并继续”才出酒店；2 天草稿“部分可校验” | 交通方式明明已说却又被问；确认回显 `交通方式：；` 为空；酒店偏好第二轮才问 |
| 2 | `3979a54` | 无确认卡，直接出 2 家乐天酒店 | 模型在文字里追问：是否接受超预算酒店、节奏、到达/离开时间；没有出草稿 |
| 3 | `4ee8897` | 同一轮无需回答问题，直接出酒店 + 2 天草稿，并写明假设 | 面板里“确认保存”灰色：唯一硬冲突是“住宿报价超过预算上限，请先接受预算放宽…” |
| 4 | `c8a2943`（超预算降级为警告） | 校验“冲突 0 · 未知 11”，“确认保存此版本”可点，点后变成“正式行程 · V1”，可导出 ICS | 默认“标准节奏”未显示在条件区（之后已修，待部署） |

线上 api 日志（第一次真模型运行）：9 次模型请求全部 200，无拦截、无报错，在“单次运行 ≤12 次 HTTP”的限制内。

- 前端瘦身与文档对齐：[2026-10-19-code-slimming-web-and-docs](2026-10-19-code-slimming-web-and-docs.md)
