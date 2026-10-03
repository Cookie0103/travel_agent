# 旅行条件、事实、行程及预订业务规则

不依赖本项目其他层，不依赖外部 SDK。

入口：`execution.py` 定义 RunContext、会话引用、应用事件和执行结果。
`catalog.py`是Place/Article/Source契约；`opening_hours.py`只解析已支持的京都营业时间子集，其他返回unknown。
关键流程：服务端注入业务身份 → runtime 事件 → CLI/API；SDK 原始类型不进入领域层。
不变量：遵守 AGENTS.md 的分层规则，不在导入包时执行网络或业务写操作。
