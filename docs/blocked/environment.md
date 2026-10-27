# 阻塞记录

- 2026-10-21（进度展示 P-103）：前端 228 tests/typecheck/lint/build 和 dev check、SDK 事件 2 tests 已通过；真实 PG `test_runs.py --maxfail=1` 连接超时，未完成集成复验及提交质量关卡。Docker 查询当前返回访问受限；未改权限、未启动 Desktop、未绕过钩子。改动在本机，恢复步骤见[当前批次 P-103](../plans/2026-10-19-session-log.md)。

- 2026-10-05T03:01:12.136047+00:00 — dev db-up: Docker 引擎不可用；启动 Docker Desktop 后重试。

- 2026-10-05 已解除：两处残留运行时套接字阻挡Docker启动；可回退保留临时目录后Docker28.5.1运行，dev db-up退出0，项目既有PostgreSQL Healthy。凭据、配置和数据库卷未修改；详情见[执行计划](../archive/execution/travel-agent.md)。

- 2026-10-21：保存项目长期方法约定时，正常 commit 的 dev check 通过，离线测试为 1854 passed、2 failed、605 errors、1 skipped、4 deselected；PostgreSQL 连接超时，docker info 确认 Docker Desktop Linux 引擎管道不存在。另已独立复现既有 write_transcript 的 Windows 相对路径分隔符失败，其余一项失败未单独定位。文档已本地保存，提交与推送被钩子阻止；不绕过检查、不自动启动 Desktop 或扩大到无关修复。恢复步骤与范围见[当前批次记录](../plans/2026-10-19-session-log.md)。
