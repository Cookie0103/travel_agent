# Skill 触发体检

VERIFIED · 2026-11-28。表中实测来自 D5 的 24 道非留出题与触发清单的交集。
分母表示实际覆盖的例数。加载增益需同题开关对照，D5 只运行了一种配置。

| Skill | 触发召回 | 误加载率 | 字符数 | 最近评测 | 加载增益 |
| --- | --- | --- | ---: | --- | --- |
| hotel-comparison | 1/1 | 0/2 | 1248 | 2026-11-28 | 待 E5 |
| itinerary-revision | 1/1 | 待测 | 515 | 2026-11-28 | 待 E5 |
| multi-city | 1/1 | 待测 | 365 | 2026-11-28 | 待 E5 |
| budget-relaxation | 1/1 | 0/2 | 853 | 2026-11-28 | 待 E5 |
| external-errors | 1/1 | 待测 | 259 | 2026-11-28 | 待 E5 |
| repair-limit | 待测 | 待测 | 321 | 待测 | 待 E5 |

## 服务端信号夹具

| Skill | 用例 | 实际路由符合预期 |
| --- | --- | --- |
| multi-city | 确认两个住宿段 | 是 |
| multi-city | 只更新单城 | 是 |
| multi-city | 分段报价 | 是 |
| budget-relaxation | 实际进入放宽档位 | 是 |
| budget-relaxation | 正常报价 | 是 |
| budget-relaxation | 查看已拒绝的放宽结果 | 是 |
| external-errors | 查询超时 | 是 |
| external-errors | 一次成功 | 是 |
| external-errors | 重试后恢复 | 是 |
| repair-limit | 已用完修复轮次 | 是 |
| repair-limit | 正常暂存 | 是 |
| repair-limit | 最后一轮修复成功 | 是 |

## PostgreSQL 集成复核

现有 `validate_itinerary` 集成用例经过真实执行器并检查其 `tool_finished` 事件。最后一轮允许的校验无 Skill 附带，
后一次达到修复上限时只附带 `repair-limit` 并记录 64 字符内容哈希。D5 中该项仍无样本。
上述集成检查、四项服务器信号的哈希记录检查和跨会话记忆检查合计 3 passed。
修复上限的服务端触发可就此验收，加载后的业务增益继续由 E5 的对照实验衡量。

## 用例预期

### hotel-comparison

- `p2-commerce-1-01` · 加载 · 有含早餐报价，用户要求比较
- `p2-out-of-scope-1-01` · 不加载 · 范围外请求，没有报价
- `p2-ambiguous-1-01` · 不加载 · 日期未定，先澄清

### itinerary-revision

- `p2-local-edit-1-01` · 加载 · 已有草稿，只换下午一个项目
- `p2-main-flow-1-02` · 不加载 · 没有旧稿，第一次规划
- `p2-local-edit-1-02` · 加载 · 更改单日时段并保留其余项目

### multi-city

- `p2-main-flow-1-01` · 加载 · 首段与次段均需选住宿
- `p2-main-flow-1-02` · 不加载 · 单城市住宿
- `p2-main-flow-1-04` · 加载 · 一晚后转场的短住宿段

### budget-relaxation

- `p2-fault-1-01` · 加载 · 供应商查无房，服务端返回住宿诊断
- `p2-memory-1-01` · 不加载 · 没有查询住宿
- `p2-ambiguous-1-01` · 不加载 · 入住日期未知，无有效报价可放宽

### external-errors

- `p2-fault-2-01` · 加载 · 已观察到一次 HTTP 429 后恢复
- `p2-main-flow-1-02` · 不加载 · 供应商正常返回，未重试
- `p2-fault-2-02` · 加载 · 带已知住宿条件的重试恢复

### repair-limit

- `repair-cap-exhausted` · 加载 · 明确返回 repair_limit
- `p2-main-flow-1-02` · 不加载 · 正常暂存，未到上限
- `repair-last-round-success` · 不加载 · 最后一次允许的修复成功
