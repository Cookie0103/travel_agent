# 三段可重放演示

默认离线；不需要模型key、不会调用真实模型或真实酒店。模型实测必须另用已授权入口，绝不能删除账本换取请求。先在项目根目录运行，测试所需本地PG须已启动。

## 1. 业务闭环与重建后读取

```text
uv run python scripts/dev.py stack-up
uv run python -m scripts.smoke_demo
uv run python scripts/dev.py stack-down
uv run python scripts/dev.py stack-up
uv run python -m scripts.smoke_demo --verify
```

打开127.0.0.1:3100，创建演示会话、填写京都11月3–5日/2成人/无儿童/1房/JPY50000/9点/步行，比较→生成→确认→只改第二天下午→再确认。固定脚本用于检查业务，不叫模型自主规划。观察模拟价格/来源、未知税和路线估算警告、仅一项差异、锁/版本拒绝。烟测还验证重复确认同版本/同订单、其他用户404和live403。
重建后verify只GET/SSE，正式V2、原订单和三run保留，补发不重调模型。停止不删卷；本次已有[截图与记录](M4.md)。

## 2. 丢响应对账与进程恢复

```text
uv run python -m pytest tests -k "real_http_lost_order_response_reconciles_after_service_restart or confirm_process_kill_on_both_sides_of_supplier_commit_queries_before_retry" -q
```

产品流程是模型工具先hold、用户确认API才POST订单。本段测试直接调用BookingService/SupplierService验证真实PG+本机HTTP故障，不经过SDK或确认HTTP API：供应商提交后断响应，客户端unknown/order_id未知。查询500仍unknown；重建服务后查询client_ref，booked返回同订单，重复确认保持同结果。kill对照分提交前/后验证最终0/1订单，不靠内存模拟事务；模型/API边界另有SDK与HTTP回归。
代码从[BookingService.confirm/_order/reconcile](../../backend/services/bookings.py)到[供应商事务](../../mock_supplier/service.py)与[回归](../../tests/integration/test_bookings.py)读。unknown是尚不确定，不等于failed，也不能由模型自选重新下单。

## 3. 失败Trace与归因/修复

```text
uv run python -m pytest tests -k "single_injected_root_is_located_from_actual_tool_and_database_facts or wrong_or_disproved_attachment_is_unknown or real_sdk_terminal_limit or sdk_complete_three_day_chain" -q
```

五种实际工具/PG/HTTP单故障注入附同run/调用/时间/版本事实。Trace只定位发生位置；归因还需要业务版本、实际参数/Evidence、供应商请求和提交事实。错附件/多根因/无证据保持unknown；恢复后成功不当最终失败。
再看[真实箱根输入失败与修复](../evidence/m26-failure-regression-2026-10-03.json)、[三日规划的失败和SDK修复](../evidence/sdk-terminal-planning-2026-10-03.json)。模型dev实测与这些确定性注入分开；未完成的三独立真实坏例不拿注入凑数。私有完整Trace/回答只在.cache，公共材料仅脱敏指标与标签。

预期：测试通过，保留所有原反例；不是每个评测案例都通过。完整冻结集三轮离线有9/120规则通过，固定搜索替身不能规划，这个结果保留，不改期待来变绿。详细[评测边界](../../eval/README.md)和[集中源码入口](learning.md)。
