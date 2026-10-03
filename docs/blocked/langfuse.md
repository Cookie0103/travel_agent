# Langfuse UI 验收缺少外部配置

2026-10-03，M0.5：`.env` 中 Langfuse public key、secret key、base URL 均未配置（只核对是否为空，没有记录值）。
自托管官方栈需要本项目已排除的 Redis 等组件，按 ADR-000/005 使用 Cloud 导出选项。
本地 OTel Trace、导出接口及其离线测试继续实施；Langfuse 中查看真实 Trace 的链接/截图保持待验收。
这不阻塞评测、数据库业务或前端开发，也不要求用户现在中断工作去注册。
