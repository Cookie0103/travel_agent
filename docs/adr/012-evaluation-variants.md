# ADR-012：评测对照复用同一SDK与业务边界

状态：接受实施；依据design/05 §4，不新增依赖或第二套runtime。

现有固定workflow只覆盖B1。增加私有evaluation_variant配置，用户消息API不接收：full为当前完整配置（含原生压缩及长期偏好）；no_tools为B0，不注册工具、不注入数据库事实、不保存/恢复业务checkpoint；no_skills仅移除load_skill；no_preferences仅不注入当前持久偏好值，仍保留旅行条件和当前合法对话；no_repairs仅允许首次校验，取消反馈后修复轮次，最后候选暂存/用户确认仍走原业务校验。

parent guard与worker共享工具集合定义。非full对照仅单轮、全新SDK会话，禁止与固定workflow或语气评审混用；每例已有独立业务身份，避免跨配置resume。默认full行为及全部权限/HTTP/工具/费用边界不改。关闭偏好不清空数据库，不移除偏好删除墓碑对历史的保护，不将当前明确条件当作长期偏好删掉。

评测manifest记录具体variant、实际schema及Skills、初始状态/数据/模型/代码hash；同一版本用例可分别运行，原评分/冻结期待不变。FixtureRuntime不会响应提示词或偏好，拒绝用它生成非full对照结论；配置机制用真实SDK/CLI与本机脚本/真实PG验证，实际模型效果另验。

历史初始决定（后续核验已替代）：no_compaction保留为显式未支持配置，启动前拒绝，不假称B2已完全分离压缩。锁定Python SDK0.2.163公开options无独立压缩开关，get_context_usage只读状态；settings/extra_args存在但未核验可靠关闭键。官方[设置文档](https://code.claude.com/docs/en/settings)与[缺少关闭说明问题](https://github.com/anthropics/claude-code/issues/24589)不能证明锁定CLI2.1.114支持新版键；不猜环境变量、不修改转录模拟关闭。未来验证公共能力后再启用。B3/单因素效果、纯文本首次进度和逐调用人工语义评分仍不得以脚本测试替代。

历史中间方案（下段反例已替代逐轮查询）：官方独立[环境变量表](https://code.claude.com/docs/en/env-vars)明确DISABLE_AUTO_COMPACT=1关闭自动压缩（保留手动压缩）。实际CLI2.1.114通过SDK get_context_usage同配置默认true/加开关false，两组0模型HTTP，私有能力证据1dfbd990-3589-421c-ad46-9ee51b04a4c2。因此继续实现no_compaction：仅SDK公共options.env设置该官方变量，每次query前用同一client公开状态核验确实false；不支持/返回开启则在模型请求前失败。仍保留所有工具/快照/偏好/校验，非full新会话；若意外出现compact_boundary则停止该对照而非计通过。启用前必须实测相同人工usage/阈值下默认发生压缩而对照没有压缩。上一段保留原未核验决定，不再当已验证能力的永久限制；完整B2仍不能将偏好和压缩同时关闭称作单因素。

实际带工具反例否定“每次query前状态读取”：get_context_usage触发count_tokens及非流式Messages估算，原Guard拒绝/0转发，两原生专项失败。保留该失败及原Guard，不开放新计费协议；改为只对已离线核验SDK0.2.163/CLI2.1.114启用官方env，未知版本在SDK初始化/模型请求前拒绝。已有单独零工具能力查询证明状态开关，带工具相同人工usage的实际压缩/不压缩测试负责效果保证，意外compaction仍停止。新测试假设随已验证技术方案调整，不删除原业务/预算测试或放宽费用边界。

当前配置补齐plan05明确B2：baseline_b2同时关闭自动压缩/当前长期偏好注入，保留原工具/Skill/validator；这是组合基线，不用于单因素因果结论。full=B3、no_tools=B0、固定workflow=B1、其余关闭项单列single_factor。与其他nonfull一样全新SDK/独立业务身份，不混workflow/judge；原模型/数据/结果评分及所有费用权限边界不变。CLI帮助与manifest采用“已验证版本环境开关”，不暗示每轮额外调用能力接口。
