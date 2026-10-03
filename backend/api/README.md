# HTTP 与 SSE 接口边界

入口：app.create_app；启动uv run python -m backend.server。
GET /health检查数据库；POST /demo/login仅DEMO_MODE=true开放，返回24小时演示令牌。
带Authorization: Bearer <token>调用POST /sessions、GET /sessions/{id}。
服务端解析身份，不接受客户端user_id登录已有账号；他人/不存在会话均404。
只通过services/agent调用其他项目层；当前尚无旅行执行/SSE接口，随M1.4接入。
