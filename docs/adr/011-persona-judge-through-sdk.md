# ADR-011：固定温度语气评审复用 SDK 与费用守卫

状态：已接受，工程与一次真实小样本已验；依据design/04 M0.7、design/05 §3.1。没有新增依赖或第二套runtime。

现有rubric/解析/人工配对统计可运行，但没有收费评审入口。锁定SDK的公共options没有temperature字段；不把提示词中的“温度0”当设置，也不另写Messages循环。

采用专用服务端persona_judge开关：同一run_live/隔离worker/ClaudeRuntime，固定语气rubric系统提示，候选文本仅作为用户数据，工具集合为空，不连接业务库、不续接旅行会话。该开关不暴露给模型工具或用户消息API。

仅评审路径在现有出站守卫内明确写temperature=0；必须是已核定DeepSeek模型、thinking disabled（CLI省略时显式补入）、零工具，不接受另设top_p/top_k。正常旅行请求保持原字节。先验证协议再预占/转发；请求上限、累计授权、每日额度、超时与隐式输出续接计数保持不变。记录实际转发温度，只有完整成功结果、同一模型/温度且无工具事件才能解析评分。JSON非法单列judge_error，无分数，不算任务成功或失败；运行/安全异常停止余下样本，不自动重试。

DeepSeek官方兼容表支持temperature 0–2，思考模式忽略该参数，所以必须关闭thinking：[官方Anthropic兼容表](https://api-docs.deepseek.com/guides/anthropic_api/)、[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)。官方页面直接打开超时，已从官方搜索索引核对；实现仍须实际本机SDK出站与真实小样本验证。这里只承诺发送参数，不宣称模型绝对确定性。未核验的Anthropic评审线路在启动前拒绝。

eval入口默认只准备/校验样本，显式--live才收费。输入/完整评分留私有.cache；manifest绑定源文件/rubric/样本hash，每次调用前落盘身份，逐结果flush/fsync支持断电核对。真人分数原样保留，不生成。至少20条真人配对及最终角色选择仍是外部验收，不能因自动评分工程通过标记已校准。

本机SDK实验：锁定CLI实际发送temperature=1、省略thinking；Guard评审分支覆盖temperature=0并补thinking disabled，1HTTP收到严格评分JSON，零工具事件，43专项通过。只证明工程边界；真实供应商与真人校准尚未完成。

一次真实原dev回答评审：1HTTP/0.002122CNY、实际temperature0/零工具/合法JSON，真人配对0保持pending；公开摘要见[证据](../evidence/m07-persona-judge-2026-10-03.json)。独立复核无P1/P2，56专项/check204通过；完整结果从执行计划读取。

Goal/AC审计补通用内容辅助评审：沿用现有私有persona_judge固定温度/零工具/无业务状态入口，仅新增judge_kind（persona默认、content）选择系统rubric，避免复制费用/进程/SDK/解析运行设施。content输出相关性/解释/取舍各0–5和简短reason，真人三维记录独立；从同一严格分数类型投影成原JudgeScore后按维度复用calibration，不把模型分当真人分或语气分。未知kind或在普通旅行路径设置content启动前拒绝；原persona旅行默认字节不改，禁止外部供应商/业务workflow/多prompt等原限制保持。实际facts/coverage仍用独立标注/Evidence入口，内容LLM分不能当事实真值或校准完成；本增量优先本机SDK无模型费用验证。
