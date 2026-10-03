# ADR-012：评测对照复用同一SDK与业务边界

状态：接受实施；依据plan/05 §4，不新增依赖或第二套runtime。

现有固定workflow只覆盖B1。增加私有evaluation_variant配置，用户消息API不接收：full为当前完整配置（含原生压缩及长期偏好）；no_tools为B0，不注册工具、不注入数据库事实、不保存/恢复业务checkpoint；no_skills仅移除load_skill；no_preferences仅不注入当前持久偏好值，仍保留旅行条件和当前合法对话；no_repairs仅允许首次校验，取消反馈后修复轮次，最后候选暂存/用户确认仍走原业务校验。

parent guard与worker共享工具集合定义。非full对照仅单轮、全新SDK会话，禁止与固定workflow或语气评审混用；每例已有独立业务身份，避免跨配置resume。默认full行为及全部权限/HTTP/工具/费用边界不改。关闭偏好不清空数据库，不移除偏好删除墓碑对历史的保护，不将当前明确条件当作长期偏好删掉。

评测manifest记录具体variant、实际schema及Skills、初始状态/数据/模型/代码hash；同一版本用例可分别运行，原评分/冻结期待不变。FixtureRuntime不会响应提示词或偏好，拒绝用它生成非full对照结论；配置机制用真实SDK/CLI与本机脚本/真实PG验证，实际模型效果另验。

no_compaction保留为显式未支持配置，启动前拒绝，不假称B2已完全分离压缩。锁定Python SDK0.2.163公开options无独立压缩开关，get_context_usage只读状态；settings/extra_args存在但未核验可靠关闭键。官方[设置文档](https://code.claude.com/docs/en/settings)与[缺少关闭说明问题](https://github.com/anthropics/claude-code/issues/24589)不能证明锁定CLI2.1.114支持新版键；不猜环境变量、不修改转录模拟关闭。未来验证公共能力后再启用。B3/单因素效果、纯文本首次进度和逐调用人工语义评分仍不得以脚本测试替代。
