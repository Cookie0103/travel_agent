# 工作台生成契约

web-openapi.json由scripts/export_web_schema.py生成，不手工编辑。
包含FastAPI接口与服务端卡片/事件模型；不需要数据库或凭据。
前端openapi-typescript生成api-types.ts，Python测试检查契约漂移。
