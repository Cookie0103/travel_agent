# 旅行 Agent 的应用策略

职责：旅行 prompt、受控 Skills、当前条件/Evidence 上下文与任务结束状态。
通用模型/工具循环交给 Claude Agent SDK，经 providers 接入；此包不直接 import SDK。
入口：尚未实现，当前为占位；M0.3 定义边界，M0.4 接 CLI。
关键流程：读取业务快照 → 调 SDK 适配 → 接收应用事件 → 展示已校验结果。
不变量：数据库业务状态为事实来源；不把 SDK 会话当事务，不越过工具校验或页面确认。
