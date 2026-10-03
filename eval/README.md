# 评测用例、评分与报告

入口：`uv run python scripts/dev.py eval-dev`，默认固定 FixtureRuntime + 实际搜索工具。
授权 live：`uv run --env-file .env python scripts/dev.py eval-dev --live`，复用 CLI 的 SDK / 请求守卫。
可用 `python -m eval.run --case-id <id>` 指定样本；默认30条均运行，不继承上游skip。

业务评测：`uv run python -m eval.run --database`，复用真实本地PG与应用旅行工具。
固定顺序：加`--workflow search|hotel|itinerary`；不带时自主选择。各组使用同Case/input/数据/schema/SDK；固定组只限制工具阶段，参数仍由模型决定。不是另写运行循环。
真实小样本：`uv run --env-file .env python -m eval.run --database --live --case-id hotel-complete-control --max-attempts 6`，另一组加`--workflow hotel`；需已有授权，累计/每日预算不变。自定义请求上限只用于DB模式，1–12，默认4；不自动重跑失败。
数据库案例逐个创建独立评测用户/session，不读现有用户行程；initial_state只支持明确request条件。导入既定目录快照，报告单列actual数据版本与hash，历史Case标签保留。
目录空才导入；已有目录与版本快照不符则拒绝，不覆盖或删除原数据。报告绑定实际目录hash。

调用链：load_cases → observe → Agent / run_live → grade → JSONL和summary。
每条结果立即flush/fsync到 `.cache/eval/<新运行ID>/`；中断后保留已发生费用与已完成案例，不自动重跑。
manifest绑定HEAD、dirty和实际代码/用例/fixture/prompt/价格文件/schema哈希。联网前attempts.jsonl记录case与服务端身份；用该会话查`.cache/sessions/<user>/<session>/report.json`和费用账本，不能仅凭缺结果认定没花钱。
运行异常停止本轮后续案例，业务规则失败继续；未跑和异常单列，不计入规则分母。
工具规则检查名称许可、开始/结束配对、成功/空结果；文本仅为弱关键词规则，不证明语义、事实和相关性。
规则未通过也正常输出报告（退出0）；执行/规格/输出异常退出1。测试必须断言实际分数，不能仅看命令退出码。
不变量：离线不调用模型；期待规格不给被测Runtime；原规划标准不因脚本能力改变；内部源码与私有全文不进Git。
DB离线仍是既有FixtureRuntime搜索脚本：能执行真实工具，不能证明自主规划/固定编排质量；空数据与顺序失败如实报告。工具数/真实HTTP/时延/原币种费用分开；usage缺失或只采到部分HTTP时tokens为null，不编造零值。
每条模型响应是私有调试数据；公共baseline只导出身份/用量/规则结果摘要。
