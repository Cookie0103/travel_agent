# 2026-10-03：整理目录与解释当前状态

## 当前检查点
- 用户请求：整理根目录、集中报告、解释目录职责和 M0.1 实际进度。
- 起点：wip/M0.1；上轮 54 个文件改动已暂存、尚无任务提交。
- 范围：文档导航、阻塞记录搬迁及相关脚本/测试路径调整、本机隐藏缓存目录；不开始 Agent 业务任务。
- 整理已完成；尚未完成的 M0.1 问题继续保留，不因本次整理宣称 Agent 已可用。
- 历史命令记录和验收输出不重写；旧补丁仍是 10 月 2 日现场。

## 操作流水
1. 只读核对 Git 状态、根目录清单、AGENTS、README、M0.1 规格与审阅、BLOCKED、开发脚本和测试；搜索 BLOCKED/pre-commit 的引用。
2. 确认 data 是数据文件与导入代码，domain 是业务对象/规则，persistence 是数据库访问；当前这些目录均未实现业务。
3. 查看已安装 pre-commit 的默认配置常量与 Git hook，确认根目录配置是现有读取位置；保留该配置，不搬到文档目录。
4. 准备将根 BLOCKED.md 移入 docs/blocked/2026-10-02-m0-core.md；今后开发脚本的环境故障写 docs/blocked/environment.md。
5. 后续命令与输出记录在同名 commands.jsonl；重要编辑、验证与最终状态继续追加本文件。
6. 第一次提交编辑补丁时，工具拒绝了对同一文件同时 Delete/Add 的写法，整份补丁未应用；随后改为 Update，编辑成功。这是编辑工具输入问题，不是测试失败。
7. 已迁移旧阻塞记录；更新 dev.record_blocked 和对应测试的目标路径（本次用户要求改变行为，因此断言路径随之更新，重复记录只写一次的断言保留）。
8. 已同步 AGENTS 的记录路径与日志约定；新增 docs/README.md、docs/blocked/README.md；重写 M0.1 通俗说明并更新主 README、backend/data/scripts/tests/mock_supplier 的职责说明。
9. 历史操作与批次报告只增加迁移提示，原始命令 JSONL 不重写；保留 .pre-commit-config.yaml 的工具默认位置。
10. 本机 .cache、.mypy_cache、.pytest_cache、.ruff_cache、.venv 已设置 Windows Hidden 属性；.git 原本已隐藏；没有删除环境或缓存，也没有更改系统的显示隐藏文件设置。
11. `dev test`：35 passed in 1.97s；其中 Docker 失败测试确认自动创建 docs/blocked、原因去重且不再生成根 BLOCKED.md。
12. 本次改动的两个 Python 文件：ruff check 通过、ruff format --check 显示 2 files already formatted。
13. 完整 `dev check` 仍退出 1：停在原有的格式化范围问题（plan/02 的示例被纳入检查）；本次没有运行写入型全仓格式化，plan/ 与 HEAD 无差异。后续 mypy 没运行到，上轮 5 个类型问题没有修复。
14. Git 差异核对：实现仅变更阻塞文件写入路径及父目录创建；测试对应新路径且保留原去重断言。没有新的业务代码、模型请求、提交或推送。
15. 最后保存：将本次整理结果更新到当前 WIP 暂存区，另导出 `.cache/2026-10-03-directory-cleanup.patch`；10 月 2 日补丁保留不覆盖。补丁和隐藏属性只在本机；实际说明和日志保存在项目中。
16. 阅读入口：docs/README.md 与 docs/review/M0.1.md。未来要运行旅行助手，仍需先收尾 M0.1，再按 M0.2～M0.4 完成真实协议验证、模型适配和 Agent 循环。
