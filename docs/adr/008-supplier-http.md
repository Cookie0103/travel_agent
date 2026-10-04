# ADR-008：模拟供应商使用现有httpx

状态：接受，2026-10-03；既定M2独立HTTP供应商路线，不新增runtime。

应用通过HTTP连接独立模拟供应商，超时/状态码/损坏JSON必须在边界显式分类，重试仅在预订服务一层。复用已经锁定用于测试的httpx 0.28.1，将其移入生产依赖，不引入另一HTTP库。

标准库urllib是同步接口，在线程包装后取消/超时边界更复杂；SDK提供模型通信，不能代替供应商业务API。httpx AsyncClient支持明确timeout、trust_env=False与不跟随redirects，公共API隔离在backend/adapters。

模拟URL只允许loopback或Compose固定服务名mock_supplier，不能由模型指定；本机默认8001。HTTP失败或响应结构/关联ID不符不能当作订单成功。429的Retry-After仅提供有限退避建议，预订服务同时限制尝试与总时长。写响应不明先对账，读失败保持unknown。

不建立通用provider/插件框架、不自动fallback真实供应商；无真实订单/付款。契约复用domain.booking与HotelOffer，测试使用真实PG及本机TCP HTTP故障。
