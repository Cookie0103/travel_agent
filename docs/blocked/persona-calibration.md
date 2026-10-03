# M0.7 角色校准外部验收

中性草案、规则评分、0–5 rubric、严格解析、固定模型/温度自动评审与配对统计已实现。eval.judge复用同一SDK/费用守卫，默认只准备，显式--live收费；零工具、无业务库，出站temperature0/关闭thinking。见[ADR011](../adr/011-persona-judge-through-sdk.md)。
一次原dev实际回答的真实DeepSeek评审：1HTTP/temperature0/合法评分/零工具；见[证据](../evidence/m07-persona-judge-2026-10-03.json)。这仅证明评审可运行，不代表校准完成或模型整体语气质量。
仍需最终角色选择、至少20条真人评分及同一评审模型配对；当前真人配对0，一致率为null。输入/原回答/完整评分留私有缓存，工具不代填真人分。准备与调用入口见[校准说明](../../eval/calibration/README.md)。此项不阻塞其他开发，也不成为逐任务批准关卡。
