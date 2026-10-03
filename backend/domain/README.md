# 旅行条件、事实、行程及预订业务规则

不依赖本项目其他层，不依赖外部 SDK。

入口：`execution.py` 定义 RunContext、会话引用、应用事件和执行结果。
`catalog.py`是Place/Article/Source契约；`opening_hours.py`只解析已支持的京都营业时间子集，其他返回unknown。
`travel_request.py`共用条件/schema与set/clear规则；同日旅行合法，酒店另检查至少一晚。
`evidence.py`检查事实的适用条件、版本、时效；来源缺失时status为unknown，不交给模型自行补全。
`hotels.py`计算模拟房晚/税费与同口径比较；`itinerary.py`定义只引用证据的行程和路线契约。
`validator.py`纯校验日期、整段营业时间、相邻路段、重叠和预算；未知不算满足。
`plans.py`保留稳定item_id，局部增改删和锁定校验；初始草稿的新ID仅由服务端生成。
关键流程：服务端注入业务身份 → runtime 事件 → CLI/API；SDK 原始类型不进入领域层。
不变量：遵守 AGENTS.md 的分层规则，不在导入包时执行网络或业务写操作。
