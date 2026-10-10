# HTTP 与 SSE 接口边界

入口：app.create_app；启动uv run python -m backend.server。
GET /health检查数据库；POST /demo/login仅DEMO_MODE=true开放，返回24小时演示令牌。
GET /articles、/articles/{id}公开读取已验证快照和许可，不创建身份、Evidence或执行；空目录503、未知ID404。
带Authorization: Bearer <token>调用POST /sessions、GET /sessions/{id}。
服务端解析身份，不接受客户端user_id登录已有账号；他人/不存在会话均404。
消息/状态/取消/SSE接口调用RunService；事件读取不重新运行模型。
GET /plans/{id}、GET /plan-drafts/{id}读取本人历史/草稿及需刷新证据。
POST /plan-drafts/{id}/confirm才保存正式版本；PATCH /plans/{id}/locks由用户设置锁定项。
只通过services/agent调用其他项目层；模型工具中没有确认保存或锁定接口。

GET /sessions与/sessions/{id}/runs经HistoryService按当前身份keyset分页；空结果/401/404/503区分，不重放模型。
