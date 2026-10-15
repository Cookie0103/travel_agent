# 旅行工作台

Next.js App Router / React / TypeScript；入口src/app/page.tsx，业务状态在use-workspace。
导航：/articles攻略列表与全文 → 明确引用到工作台；/plans只读当前身份已确认的正式行程。
攻略阅读不创建会话；引用只填消息。页面卸载撤销旧请求写回，读取失败可重试原plan_id。
API请求/输出类型由FastAPI和服务端卡片模型生成，不在页面重算价格或校验。

需要Node24+、pnpm11；从仓库根目录：

```text
uv run python scripts/dev.py web-setup
uv run python scripts/dev.py api
# 另一个终端
uv run python scripts/dev.py web
```

打开http://127.0.0.1:3000。创建演示会话后直接对话提条件，右侧仅用于纠正；比较→生成→确认→修改→确认。
默认固定免费脚本会调用真实业务工具/PG；重复景点用于展示状态，不代表模型规划质量。
真实模式须另以python -m backend.server --live启动API，并在网页显式选择/允许本次费用。
预算和供应商授权仍由服务端检查，页面不会接触供应商密钥。

验证：dev web-check（类型/lint/Node原生测试/build）；契约变化时dev web-generate。
每次build替换.next；本地standalone需补当前.next/static到.next/standalone/.next/static并重启，再查脚本200和Chrome工作台；命令见docs/operations/product-v2.md的P73。
缓存由pnpm-workspace.yaml限定项目.cache；不执行unrs-resolver安装脚本。
金额使用服务端字符串；模型不能代替确认。刷新恢复当前标签页身份/执行/正式行程。
未知响应的消息保留原client_message_id，用户明确重试；重连只读事件，不重发消息。
对话按服务端轮次列表恢复，history.ts负责按run_id/sequence合并早页及保留本标签全文。
实时原回复沿用服务端临时保留策略，跨重启历史可能只显示已持久化的说明。

旅行菜单从归属历史接口读取；新建旅行沿用已有身份，京都等旧旅行仍可切回。localStorage只保留token/current session；模型选择和绑定身份/旅行的临时outbox使用sessionStorage。未获响应的消息需在原旅行明确重试；服务端确认接受后清outbox，不自动重放。
