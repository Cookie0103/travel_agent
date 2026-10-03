# 模拟酒店供应商

独立FastAPI进程，服务端口8001；运行 `uv run python scripts/dev.py db-migrate` 后执行 `uv run python scripts/dev.py supplier`。
`python -m mock_supplier.server --faults` 只用于显式故障演示。

- POST /holds：完整有效模拟报价与稳定client_ref，返回15分钟hold。
- POST /orders：hold_id与相同client_ref；并发/重启重复返回第一次订单。
- GET /orders?client_ref=：返回订单；暂时查无不代表失败，过期hold锁内查无才absence_final。
- X-Mock-Fault：delay / rate_limit / server_error / lose_response；X-Mock-Delay：0–5秒，默认1。
- 未显式启用故障时拒绝故障头；丢响应在订单提交后打断真实HTTP传输。

复用项目PG连接/迁移，供应商事实在独立supplier_holds/supplier_orders表；不依赖Travel用户/证据表。
报价复用现有HotelOffer/quote并对照目录，不另写价格公式。
仅绑定本机、仅模拟，无真实预订、付款或生产鉴权；模型没有下单工具。
测试见 tests/integration/test_supplier.py，涵盖真实PG/HTTP与有界清理。
