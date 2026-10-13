# ADR-024 经逐条确认的偏好事实与选择性遗忘

日期：2026-10-14；状态：实施中。依据：[本批T5、D9](../plans/2026-10-13-interaction-memory-eval.md)。不新增依赖或记忆运行时。

组合审查追加0020持久memory_forgotten_at：用户遗忘取得同一用户锁后更新边界，边界前仍running的旧来源不能再propose；后来的普通确认不能覆盖此边界。重复空DELETE保持旧公开revision幂等，但更新隐私边界，历史/待办读取使用两个截止时间的较晚者，SDK续接额外核对原PG run的时间和归属。确认卡只携带封闭待办元数据的safe_after证明，不恢复被截止的旧goal_prompt；后续删除仍裁掉待办。三个确认+两种删除迟到写入先红5项，再绿；原DELETE/SDK偏好断言保持。

画像的来源校验、CAS和删除级联见[ADR-025](025-derived-user-profile.md)。任何事实变更会清衍生正文与引用；生成途中遗忘不允许旧结果覆盖。

独立审查补充：0019新增task_runs.user_text，保存原MessageInput.text；模型prompt可以附结构化选择说明，但引用只能核对user_text。旧NULL不反推/回填，无法确认来源就拒绝提议。手动PATCH只替换实际变化字段；确认在最终scope检查所有单值与集合重复，冲突409；卡片读取复核目标和已出现的冲突；当前事实与最多100条历史分别查询，历史不能挤掉可删除的active事实。五项P2均有真实RED→GREEN回归及只读复核，无剩余P1/P2。

事实表成为唯一存储，Preferences保持既有API形状，是active long_term的interest/avoid/transport投影；其他闭合key通过独立memory快照供模型参考。当前旅行的明确条件优先。旧JSON列保留用于代码回退，但迁移后清正文；不得留下已删除内容让旧代码复活。回退只从仍active事实重建兼容投影。

模型在当前SDK轮次提出ADD/UPDATE/INVALIDATE，quote经NFKC/空白规范化后必须出现在当前owned running run用户输入中。攻略、工具结果、AI输出不授予来源资格；服务端不做语义猜测，第三方/否定/抽取质量另用E6衡量。每事实一张已有choice组件卡，服务端固定“记住/这次而已/不要记”；只有结构化点击才生效，操作与原消息/幂等事务一起提交。模型不能确认。

确认在用户锁内重新核对proposal状态和目标所有者/active状态；无冲突ADD不因前一张卡推进全局revision而全部失效。删除会把所有相关pending事实清内容并失效，从事实状态判卡stale，不在删除时锁choice，避免与消息提交的card→user顺序成环。任何事实变更推进已有preference_revision/changed_at，复用SDK checkpoint及有界回顾失效，不实现第二套缓存。

单条/全部删除清value与quote，墓碑只留身份/状态/时间；被引用摘要作废，卡片持久内容不重复复制偏好正文。原用户对话仍是用户请求保存的原始历史，业务记忆和摘要不从旧历史重新抽取。用户可在偏好页查看来源、有效区间、被取代版本并删除。

保留每字段20条和原数组顺序；事实增加内部ordinal用于兼容投影顺序，自动ADD须检查容量，不能让下一次GET验证失败。快照最多30条、2000字，只含active long_term和当前会话trip；偏好消融同时移除memory/summary，防止评测被新入口穿透。

valid_from/invalidated_at记录确认后的有效区间，created_at/last_confirmed_at记录提出与确认时间；这是有时间依据的版本历史，不声称实现完整SQL双时态查询系统。来源约束参考[MINJA](https://arxiv.org/abs/2503.03704)，更新与拒答参考[LongMemEval](https://arxiv.org/abs/2410.10813)，选择性遗忘参考[MemoryAgentBench](https://arxiv.org/abs/2507.05257)；2026-10-14再次核对三篇摘要，未把摘要未说明的机制升级成VERIFIED，论文机制不直接当本项目实测结论。
