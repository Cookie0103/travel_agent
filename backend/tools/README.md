# 工具注册、校验与执行

`search.py`保留CLI fixture；`travel.py`连接数据库的旅行工具。

入口：`contracts.py` 定义唯一工具 schema、执行接口和结构化结果。
关键流程：共享工具契约 → SDK MCP 桥接 → 注入的业务执行器。
结果正文必须带 ok/empty/error 状态，不能只依赖 MCP 的 is_error。
Pydantic 输入同时生成 schema 和验证直接调用；景点/攻略只暴露各自支持的字段。
SearchExecutor 返回带来源的 fixture 结果；空数据、参数错误和下游不可用必须区分。
不变量：遵守 AGENTS.md 的分层规则，不在导入包时执行网络或业务写操作。
TravelToolExecutor接数据库CatalogService/TravelService；schema复用Pydantic契约。
同一run串行执行，身份不由模型提供；Skills只按白名单读取，不能扩大权限。
