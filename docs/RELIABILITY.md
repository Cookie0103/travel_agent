# 可靠性边界与故障验证

设计依据：[design/02 §6](design/02-architecture.md)、[M1/M2实施规格入口](README.md)。
本文件说明需要保护什么、在哪里验证；完成状态统一看[执行计划](execution/travel-agent.md)。

| 边界 | 必须保持的规则 | 验证入口 |
| --- | --- | --- |
| 消息重试 | 相同会话+消息ID返回同一次执行；不同内容报冲突 | integration/test_runs.py |
| 并发条件修改 | expected_revision检查与状态/证据失效同事务 | integration/test_travel.py |
| 取消/完成 | 同一行锁裁决；最终状态与最终事件同时提交 | integration/test_runs.py |
| 超时/子进程 | 总期限不能被慢流延长；清理本次自有进程树 | test_sdk_lifecycle.py |
| SDK结束 | 父进程验证退出码/守卫/停止原因后才公开终态 | test_live_application.py |
| SSE重连 | 只读取已保存事件，绝不重新执行工具或模型 | integration/test_runs.py |
| 报价 | 过期、旧revision、条件不符时重新查询，不复用为当前事实 | integration/test_hotels.py |
| 保存/预订恢复 | 稳定业务幂等键；unknown先对账；SDK文件不代表事务完成 | M1.7/M2规格，验收尚待实现 |

失败必须分类返回并保存已核验业务结果，不能额外调用模型“收尾”或编造成功。
重试只在明确的一层，设置次数/总期限；模型SDK内部HTTP尝试也计入授权。
不实现C档多worker/租约/队列。第一版单进程后台任务的跨进程恢复由M2实验证明。
PostgreSQL故障测试用本次随机专用库；不mock事务，不清理用户数据库。
重启前后核对Git、数据库状态、私有SDK文件和费用账本；仅“日志开始”不能证明完成。
运行命令见[README](../README.md)，中断操作见[workflow](execution/workflow.md)，失败证据放operations/evidence。
