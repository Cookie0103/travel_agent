# 设计实施约定

目标与领域设计见[设计地图](design/README.md)，实现位置见[架构地图](../ARCHITECTURE.md)。本文件只规定如何落实设计。

- 从用户能观察的结果定义改动与验收，不能以“多了一个类/文件”当成功。
- SDK承担通用模型循环；旅行事实、约束、确认与事务由本项目确定性代码处理。
- 先搜索现有函数、schema、服务与SDK公共能力；同一规则只维护一个来源。
- 有真实重复再抽象，边界适配可以封装；不提前建设插件、通用CRUD或第二套运行时。
- 每个公开状态都解释来源、适用条件和失败；fixture/snapshot/估算/未知在展示中可见。
- 小改动使用短实施记录；复杂改动更新当前[执行计划](execution/travel-agent.md)与对应[tasks](tasks/M1.md)，保留决定、失败发现和可重放证据。
- 当前架构内的可回退选择自主实施；改变产品目标或业务安全不变量按[工作流](execution/workflow.md)处理。
- 设计和代码出现偏差时修正其实际来源，其他文档链接过去，不复制一份“新版规则”。

界面约定见[FRONTEND](guides/FRONTEND.md)，工程可执行标准见[standards](execution/standards.md)，验证缺口见[QUALITY_SCORE](guides/QUALITY_SCORE.md)。
此方式借鉴[Harness engineering](https://openai.com/index/harness-engineering/)的渐进导航、机械约束与文档维护。
