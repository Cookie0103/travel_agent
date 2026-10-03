# 评测用例、评分与报告

入口：`uv run python scripts/dev.py eval-dev`，默认固定 FixtureRuntime + 实际搜索工具。
授权 live：`uv run --env-file .env python scripts/dev.py eval-dev --live`，复用 CLI 的 SDK / 请求守卫。
可用 `python -m eval.run --case-id <id>` 指定样本；默认21条均运行，不继承上游skip。

调用链：load_cases → observe → Agent / run_live → grade → JSONL和summary。
每条结果立即flush/fsync到 `.cache/eval/<新运行ID>/`；中断后保留已发生费用与已完成案例，不自动重跑。
manifest绑定HEAD、dirty和实际代码/用例/fixture/prompt/价格文件/schema哈希。联网前attempts.jsonl记录case与服务端身份；用该会话查`.cache/sessions/<user>/<session>/report.json`和费用账本，不能仅凭缺结果认定没花钱。
运行异常停止本轮后续案例，业务规则失败继续；未跑和异常单列，不计入规则分母。
工具规则检查名称许可、开始/结束配对、成功/空结果；文本仅为弱关键词规则，不证明语义、事实和相关性。
规则未通过也正常输出报告（退出0）；执行/规格/输出异常退出1。测试必须断言实际分数，不能仅看命令退出码。
不变量：离线不调用模型；期待规格不给被测Runtime；未实现的规划标准保留失败；内部源码与私有全文不进Git。
每条模型响应是私有调试数据；公共baseline只导出身份/用量/规则结果摘要。
