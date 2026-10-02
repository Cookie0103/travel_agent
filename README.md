# 旅行规划 Agent

从攻略出发，通过对话比较酒店、生成并修改京都 2–3 天行程，确认后模拟预订。模型负责理解需求和编排工具，后端负责事实校验、约束检查和失败恢复。

技术栈：Python / FastAPI / PostgreSQL / Next.js；DeepSeek（开发）与 Claude（演示 / 对比），Anthropic Messages 格式 tool calling；MCP；OpenTelemetry + Langfuse。

当前处于设计阶段，应用尚未实现。范围、实施顺序和文档导航见 [plan/README.md](plan/README.md)。

数据来源：攻略来自 [Wikivoyage](https://en.wikivoyage.org/)（CC BY-SA），地点来自 [OpenStreetMap](https://www.openstreetmap.org/copyright)（© OpenStreetMap contributors, ODbL）。酒店与预订均为模拟数据。
