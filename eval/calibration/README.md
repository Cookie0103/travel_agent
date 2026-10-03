# 语气/内容辅助评审与真人校准

角色与rubric唯一来源backend/agent/persona；校准函数在eval/persona.py。
私有JSONL每行Sample：case_id、user_input、text、scene；真人字段由实际评审人填写。
语气使用human_score/human_rater；内容使用human_quality（三个0–5分、reason、rater），禁止混用。
`uv run python -m eval.judge <私有JSONL>`默认persona，仅准备，0模型请求。
内容加`--kind content`；拒绝空/重复/超过30条/已评分输入。
`uv run --env-file .env python -m eval.judge <私有JSONL> --kind content --live`才收费。
DeepSeek固定模型/温度0、零工具/无业务库；累计/每日额度同时满足，每条最多4实际HTTP，失败不自动重试。
同一Claude Agent SDK/Guard，转发补温度0/关闭thinking；普通旅行请求不改，候选不作为系统指令。
.cache/persona或content-judge/<新ID>保存manifest、调用前attempts、逐结果results和samples，flush/fsync。
恢复先核对持久预算/会话报告，不凭缺结果推断没花费；原回答/理由不公开。
非法JSON单列judge_error；运行/温度/身份/工具异常runtime_error停止后续，not_run不改成零分。
已评分samples补入真人分后，用`uv run python -m eval.persona <samples.jsonl>`离线统计。
内容加`--kind content`，分别复用三维校准，不再调用模型/更改输入文件。
每维至少20对、同一模型/温度0、无解析错误才达到样本条件；缺真人分pending、比率null。
语气/内容各一次真实小样本已验入口；完整模型质量、真人校准与最终角色仍未完成。
本机20条未评分准备：.cache/calibration-preparation/20261004-first20-v1/samples.jsonl。
选原full第一轮前20非空回答（17规则pass/3fail）；选择/hash见docs/evidence/calibration-preparation-2026-10-04.json。
默认准备/离线校准已验0请求、真人配对0；不是全40质量估计，没有外发候选或代填真人分。
模型内容分不证明事实准确；事实附件入口见[评测指南](../../docs/evaluation.md)。
