# 交互、记忆与评测批次操作

状态只维护在[当前批次](../plans/2026-10-13-interaction-memory-eval.md)。本文件记录可重跑命令及导出步骤，不包含凭据或私人对话。

## 本地验证

```text
uv run python scripts/dev.py db-up
uv run python scripts/dev.py format
uv run python scripts/dev.py check
uv run python scripts/dev.py test
uv run python scripts/dev.py test --path tests/integration/test_answer_history.py
uv run python scripts/dev.py web-generate
uv run python scripts/dev.py web-check
uv run python scripts/dev.py api --live
```

当前本机默认 CLI 2.1.296，压缩关闭实验的已核验名单止于 2.1.295。测试前在当前进程设置 `TRAVEL_CLAUDE_CLI` 指向本机已有的 2.1.295 文件，不改 `.env`、全局 CLI 或未知版本门禁。其他平台选择当地已有的已核验版本，不硬编码到产品代码。

模型日预算 60 CNY、累计 150 CNY 从 2026-10-13 UTC 日期起生效，HUMAN 同样受限。旧日期和旧账本格式保留，未结算预占按全额计费，不清零。供应商配额独立记账。

## Railway 对话导出到本地（方式 A）

新代码部署后，最终回答随原 `task_runs` 事务存入配置的 PostgreSQL；本批不改 Railway 部署。旧占位回答无法恢复原文。导出只读，不触发模型、供应商或订单。

1. 从 Railway 的 Postgres 服务变量取得 `DATABASE_PUBLIC_URL`，放入本机临时环境，不写入仓库。
2. 选择新的本地 JSON 路径。`--user`、`--session` 同时给出时取交集；不筛选则导出全部会话，适用于拥有数据库凭据的操作者。
3. 执行以下命令。macOS/zsh 示例中的变量，在 PowerShell 中用 `$env:DATABASE_PUBLIC_URL`；脚本默认也可读取 `DATABASE_URL`。

```text
uv run python scripts/export_history.py --database-url "$DATABASE_PUBLIC_URL" --session <会话UUID> --out <本地新文件.json>
```

输出含会话、各轮 prompt/answer、状态、时间戳和 presentation 引用，不含令牌、SDK 文件或供应商原始响应。文件含私有对话，保留在本地；脚本拒绝覆盖已有文件。

## 备选：整库备份与直接查询

生产 PG18 的备份需本机 `pg_dump` 18 或更新版本。整库备份包含更多私有业务数据，不提交到 Git。

```text
pg_dump "$DATABASE_PUBLIC_URL" -Fc -f travel.dump
railway connect Postgres
```

进入 psql 后可先 `BEGIN READ ONLY`，按用户/会话查 `task_runs`，最后 `ROLLBACK`。这些步骤供用户需要导出时执行；开发期间不连接生产数据库。

## 验证日志

本机原始日志保留在 ignored 的 `.cache/batch-2026-10-13/`，正式结果写在当前批次计划。完整测试输出与私有运行报告不提交到公共仓库。
