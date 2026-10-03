# 语气评审与真人校准

角色来源backend/agent/persona.md；同源rubric在persona.py，规则/严格JudgeScore/校准统计在eval/persona.py。
私有JSONL每行Sample：case_id、user_input、text、scene，可选真人human_score/human_rater；工具不生成真人分。
`uv run python -m eval.judge <私有JSONL>`仅准备，0模型请求；拒绝空/重复/超过30条/已评分输入。
`uv run --env-file .env python -m eval.judge <私有JSONL> --live`才收费，DeepSeek固定模型/温度0、零工具/无业务库；同时满足累计与每日授权，每条最多4实际HTTP，失败不自动重试。
同一Claude Agent SDK/Guard，真实转发补温度0/关闭thinking；普通旅行请求不改。候选只是数据，系统rubric不接受其指令。
.cache/persona/<新ID>保存manifest、调用前attempts、逐结果results和samples，flush/fsync；恢复先核对持久预算/会话报告，不凭缺结果推断没花费。
非法评分JSON单列judge_error且无分数；运行/温度/身份/工具异常runtime_error并停止后续，not_run单列，不改成零分。
`uv run python -m eval.persona <生成的samples.jsonl>`统计实际真人配对，至少20条、同一评审模型/温度0、无解析错误才达到样本条件。
缺少真人分保持pending，一致率null。一次真实小样本已验证评审工程，20真人校准与最终角色仍待验。
