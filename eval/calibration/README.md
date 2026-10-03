# 语气校准（待用户最终角色验收）

角色来源 backend/agent/persona.md；规则、0–5评审标准和解析在 eval/persona.py。
`rules`只统计可检测表述；`judge_prompt`生成评审输入；JudgeScore拒绝非整数/越界/格式错误，记judge_error。
校准输入为私有JSONL，每行Sample字段见eval/persona.py：case_id、user_input、text、scene、human_score/human_rater、judge_response/judge_model/judge_temperature。
`uv run python -m eval.persona <私有JSONL>`统计真实人工与LLM配对，至少20条、同一评审模型、temperature0才具备校准样本条件。
字段空缺保持pending；脚本不生成或代填人工分数。模型与人工相差≤1分比例单列，不编造一致性。
当前SDK公共options没有已核验的temperature控制，不使用提示词冒充温度0，也不另接无预算保护的付费评审API。
因此自动LLM评分与人工20条校准仍未验收；先保留评分设施，继续M1业务开发。
