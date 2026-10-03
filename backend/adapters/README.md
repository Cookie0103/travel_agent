# 外部服务适配边界

隔离外部服务协议；不在导入时联网。

入口：tracing.trace_report 接收私有运行报告，导出 OTel spans。
关键流程：真实事件时间 → SDK 内存 spans → 本地 JSONL → 显式可选 OTLP HTTP。
不变量：不导出正文/密钥；不虚构缺失时间/usage；导出故障保留业务结果。

supplier.SupplierClient隔离模拟HTTP，无自动重试；SupplierGateway仅隔离当前实际供应商测试，不是插件框架。

local_http.serve_http为测试/评测共享本机临时HTTP服务，随机端口、启动有界、退出关闭本次服务。
