# 开发辅助命令

这里给开发者使用，不是旅行 Agent 的业务执行代码。Agent 入口在 backend/agent，模型与工具循环由 Claude Agent SDK 执行；测试代码在 tests/。

## 目录

```text
scripts/
  dev.py        唯一开发入口：setup / check / test / db-up / api / web / eval-* / stack-* / doctor
  devtools/     dev.py 调用的本地工具，不联网
    doctor.py            只读检查 Python、uv、Node、pnpm、CLI 白名单、PG、pytest 临时目录
    check_docs.py        文档入口检查：入口文件存在、AGENTS/ARCHITECTURE 不超过 100 行、仓库内链接有效
    export_web_schema.py 从 FastAPI 生成前端用的接口契约
    fetch_upstream.py    下载固定版本的参考代码到 vendor/
  demo/         离线容器演示
    stack.py             独立 Compose 演示栈的启停
    bootstrap_demo.py    容器启动前迁移并导入快照
    smoke_demo.py        经前端同源代理跑三套离线业务演示
  live/         会连真实外部服务，需要显式授权和凭据
    smoke_live.py              一个城市的一轮真实规划
    smoke_langfuse_linkage.py  DeepSeek → PG → Langfuse 联验
    probe_hotel_sort.py        乐天排序探针
    export_history.py          只读导出线上用户旅行与对话记录
```

## 用法

```text
uv run python scripts/dev.py check                 # ruff、mypy、分层契约、文档入口
uv run python scripts/dev.py test                  # pytest，排除 live
uv run python -m scripts.demo.smoke_demo           # 需先 dev.py stack-up
uv run python -m scripts.live.smoke_live --execute --city 大阪
```

子目录里的脚本一律用 `python -m scripts.<组>.<名>` 运行。环境阻塞（例如 Docker 没启动）由 dev.py 自动写入 docs/blocked/environment.md。

## 不变量

前一步失败就返回失败，不能让后一步的成功掩盖它；默认不调用真实模型；`live/` 下的脚本不进 CI。
