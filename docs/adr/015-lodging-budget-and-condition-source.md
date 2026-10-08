# ADR-015：住宿预算分项、现算预算关系与条件来源

状态：接受，2026-10-08；依据用户 D5/D6/U1、批次 §3.5 与 design/03 §2/§5。先定契约，T3.3/T3.7 实施；不新增依赖或第二套解析运行时。

## 预算模型与选项

全程 `budget`/`currency` 保持现有含义；新增可选 `lodging_budget`：

```json
{
  "amount": {"lower": "20000", "upper": "30000"},
  "basis": "per_room_night",
  "currency": "JPY"
}
```

- amount 用 Decimal；lower/upper 可分别为空，但至少一个非空，已知金额须 >0、最多 12 位/2 位小数，两个均知时 lower≤upper。明确单值“每房每晚3万”存 lower=upper=30000；“不超过3万”只存 upper；“至少2万”只存 lower。不把未说出的端点补成 0。
- basis 是 per_room_night 或 total；currency 为大写三字母币种，由已明确的币种/现有日元场景写入。全程预算仍遵守当前只支持 JPY 的契约；住宿分项可以保留其他明确币种，但与 JPY 不同即无法判断，不换汇、不将其转换为可比较的日元报价。
- lower 是用户预算表达的下限，不是酒店必须花到的最低消费；便宜但合适的酒店仍可推荐。比较报价以住宿上限作上限判断，不按下限排除便宜选项。
- 采用保留区间两端；不选只存上限（无法区分 D6 冲突与警告），不选另存 conflict 布尔标志（可能与值失同步），不选预算冲突拒绝写入（丢失用户事实）。

## 保存与 validator 的唯一判定

Pydantic 仅拒绝结构非法/负数/反向区间/无效日期；两个预算的业务矛盾仍保存。沿用会话行锁、expected_revision、set/clear、规范化后的语义 diff；一次语义更新增加一次 revision，无变化不增。

由一个纯领域计算供 validator、酒店比较前置检查、UI/工具提示共同使用，不在客户端和适配器各算一套，不持久化判定：

| 前提 | 结果与行为 |
| --- | --- |
| per_room_night | 每个已知端点 × rooms × (end_date−start_date 的晚数)；数量未齐则无法判断，不默认 1 房/2 晚 |
| total | 端点本身即住宿总额，无需晚数/房间数 |
| 下限 > 全程预算 | conflict；两个原值保存，先对话追问，以哪个为准；解决前阻止酒店比较（包括绕过先置搜索的直接比较入口） |
| 下限不超/未知，只有上限 > 全程预算 | warning；不升格 conflict，不调整值，告知可超预算的范围 |
| 两个预算任一个未知、必要数量未知、币种不同 | unknown/无法判断；不估算、不换汇、不宣称预算已满足 |
| 已知上限 ≤ 全程预算 | 预算分项上限未超；不能据此宣称实际行程所有费用齐全 |
| 仅下限已知且不超过全程预算 | 上限未知，关系仍不能完整判断；若下限已超仍是 conflict |

当天往返是合法日期；per_room_night 换算为零住宿晚数，沿用酒店前置规则不搜索住宿；不创造住宿报价。total 的用户金额仍原样保存与比较，冲突时追问。

行程 validator 在生成与确认时都检查预算关系。存在 conflict 的草稿 ValidationReport.status=conflict，沿用不可确认规则。范围 warning 用现有 ValidationCheck.status=unknown 配合独立 code/中文“预算警告”说明，汇总 partial（可确认但有未核实风险），不新增第四种 CheckStatus；无法判断同样 unknown，但 code/提示区分。不向旧报告 payload 添加旧 Pydantic 不认识的 severity 字段。

用户回答后仅更新其明确改动的那个字段；例如全程5万、1房、每晚3万、2晚原值都保存，计算6万→conflict；回答“全程改成7万”只改 budget，住宿仍3万，revision 正常增加。每晚2–3万×1房×2晚对全程5万是 warning。只给全程6万时住宿为 null，不按比例拆、不当每晚价。

## 来源与对话提取

- GET request 增量返回 `field_sources`：条件字段名 → conversation/user_form/none；无记录/旧数据/清除字段显示 none，不推测旧值来源。服务端从调用入口确定来源：PATCH API=user_form，update_travel_request 工具=conversation；来源不由模型或表单自由声明。
- 对话工具新增可选 `explicit_fields`（必须是本次 set/clear 字段的子集）。已标 user_form 的字段，只允许属于 explicit_fields 的明确新值覆盖；未声明的推测提取保留原值并要求澄清。明确更新的回执返回实际 changed_fields/来源与“已按对话更新…”提示，助手向用户告知；模糊表述不能假称更新成功。提取仍由现有 SDK/工具契约完成，离线演示复用同一 patch/来源优先规则，不另建通用自然语言解析器。
- 来源入口与规范化后的 explicit_fields 都须参与 operation identity：同一 set/clear 的模糊提取与明确更新可能产生不同结果，不能复用前次 no-op；不另造幂等框架，复用现有 operations.key/result。
- 相同值的确认不增业务 revision；必要的来源标注可在同一事务更新元数据，不使草稿/证据失效。缓存命中不能只据业务 revision 返回旧 field_sources，须从当前行重读来源构造回执；旧操作重试不能覆盖后来更新的来源。clear 删除事实、来源归 none。金额/兴趣来源变化不刷新入住报价，入住条件变化沿用已有 evidence_conditions/invalidated_kinds。

## 持久化、部署与回退

直接把新键写入现有 conditions JSONB 会被旧后端 `extra=forbid` 拒绝，不能称为兼容。因此选一列增量 nullable JSONB `request_details`，仅保存 lodging_budget、field_sources 与来源对应的 revision；既有 conditions JSONB 继续只保存旧模型认识的字段。一个值只有一个持久化位置，不在两列重复保存预算。

T3.3 在现有 Alembic 链增加迁移（届时取下一个编号），保留列与数据、不 drop/reset；旧行 null 读为住宿未知/来源 none；旧 INSERT/UPDATE 不要求新列。新后端从旧 conditions+details 合并模型，写时拆分；若旧后端曾改变 revision，来源 revision 不匹配时仅撤销不可信来源标签，不编造新来源或丢弃住宿金额。

- 旧前端 + 新后端：旧 PATCH 未带住宿字段即保持其值；缺字段不是 clear，新 validator 仍执行 D6。
- 新前端 + 旧后端：返回缺新字段意味着能力未就绪；UI 明确提示新预算/来源功能暂不可用，不能 silently 丢弃住宿金额后声称已保存，也不提交会被旧契约拒绝的新字段。既有条件/对话功能仍可用。涉及未受支持预算能力的比较/确认不冒称已校验。
- 回退保留新列；旧条件可读，新预算细节保留待恢复新版本。证据/草稿内嵌 TravelRequest 的序列化须投影兼容字段，新预算仍以 request_details 为当前事实；旧后端不具备 D6 功能，回退期间 UI 不宣称新预算保证有效。新实现必须测试旧模型实际读回，而非只读 schema 推断。

## 必须验证

领域：conflict / warning / unknown 各至少一例；相等边界、total 无数量、缺晚数/房间数、不同币种、单端区间、未知预算、Decimal no-op、不排除低价酒店。真实 PG：冲突两值都落库、回答只改指定字段/revision、默认旧行、旧 PATCH 保留新值、来源事务与旧模型读取兼容；同补丁模糊 no-op 后明确更新不复用旧结果、来源 no-op 更新后旧操作重试返回当前来源；确认再校验 conflict。对话/UI：不填表直接发消息、空字段不注入样例、来自对话标签、手填优先/明确改值回执、所有模式共享规则。ADR 确立契约不等于这些实现或实测已完成。
