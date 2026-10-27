# 脱敏证据

JSON 结果与浏览器截图，**只存脱敏数据**：不含 token、密钥、私人对话原文、完整模型回答（这些留在 ignored 的 `.cache/`）。引用证据时以批次计划/案例/QUALITY_SCORE 的链接为准；本页只帮你按文件名前缀找到一组证据。共约 220 个文件。

| 文件名前缀 | 来自 | 内容 | 看它的上下文 |
| --- | --- | --- | --- |
| `sdk-*`、`travel-query-*`、`m05-*`…`m07-*`、`calibration-*`、`content-review-*` | 2026-10-03/04，M0–M0.7 | SDK 真实往返、旅行工具查询、Langfuse 云上传读回、基线与范围回归、语气评审、校准准备 | [archive/review/M0.md](../archive/review/M0.md)、[blocked/langfuse.md](../blocked/langfuse.md)、[persona-calibration](../blocked/persona-calibration.md) |
| `m11-*`…`m36-*` | 2026-10-03/04，M1–M3 | HTTP 烟测、工作台页面/移动端、失败回归、偏好保存与删除、酒店比较、抹茶数据 | [review/M1.md](../review/M1.md)、[M2](../review/M2.md)、[M3](../review/M3.md) |
| `m41-*`、`m42-*` | 2026-10-03/04，M4 | 容器重启、冻结评测 40×3 的多组结果（离线/无工具/真实模型/受控扫描/配对比较） | [review/M4.md](../review/M4.md)、[QUALITY_SCORE](../guides/QUALITY_SCORE.md) |
| `product-v2/` | 2026-10-08 起 | Product V2 批次的条件、恢复、对话回归等 P-条目证据（约 87 个文件，文件名前缀对应 P-编号，如 `p56-59-*`） | [批次计划](../plans/2026-10-08-product-v2.md)、[operations/product-v2.md](../operations/product-v2.md) |
| `2026-10-10-*`、`2026-10-11-*` | 多城市/分段选酒店批次 | 部分行程恢复、分段酒店、五日草稿的浏览器截图与真实多城市结果 | [多城市批次](../plans/2026-10-10-multi-city-pacing.md)、[分段选酒店](../plans/2026-10-11-segment-hotel-selection.md) |
| `t1-*`…`t7b-*` | 2026-10-13/14 交互·记忆·评测批次的任务 T1–T7 | 回答持久化、节奏点选、预算放宽、确认记忆、派生画像、Langfuse 关联、评测设施与真实抽样、乐天排序探针 | [批次计划](../plans/2026-10-13-interaction-memory-eval.md)、[面试案例](../review/cases/2026-10-13-interaction-memory-eval.md) |
| `f5-*`…`f13-*` | 2026-10-14 修复批次 F5–F13 | 重算分、标注、分诊一致性、控制器 trace、DeepSeek 验收、最终重评 | 同上 |

## 常被引用的关键证据

- M4 冻结评测：[当前版本三轮](m42-current-full-repeat-2026-10-04.json)（92/120 规则通过，26 规划候选均 partial）、[首次真实 40×3](m42-model-repeat-2026-10-03.json)（94/120）、[零工具三轮](m42-no-tools-repeat-2026-10-03.json)、[完整配对统计](m42-paired-comparison-2026-10-03.json)、[有限同版本测量](m42-controlled-sweep-2026-10-04.json)（97/120）。均为规则通过数，不当事实准确率或人工校准。
- M0/M1 基线：[旅行工具真实查询](travel-query-2026-10-03.json)、[基础 API 真实 HTTP 烟测](m11-api-smoke-2026-10-03.json)、[初始真实评测](m06-baseline-2026-10-03.json)、[范围坏例回归](m07-scope-regression-2026-10-03.json)。

新增证据放此目录；多文件的一次实验建子目录。文件名带日期与任务编号，并在对应批次计划/案例中链接。
