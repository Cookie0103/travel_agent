# ADR-031：记忆改为run结束后的异步抽取

状态：accepted（2026-10-26）。修改[ADR-024](024-confirmed-memory-facts.md)的“模型在当前SDK轮次提出”；事实存储、逐条确认、遗忘边界、合并确认卡全部沿用。

## 背景

主agent在对话中同步调用`propose_memory`：prompt要为它维护四条规则（第77–80条），规划中途调用还会分散工具次数；抽取只能看本轮原话，跨轮指代（“以后都按刚才说的”）无法处理。

## 决定

- 主agent不再有记忆工具。真实模型轮次（deepseek/claude）以`completed`落库后，`RunService`在后台启动`MemoryExtractor.extract`；离线模式、失败/取消/超时的轮次不抽取。抽取失败只写日志与TRACE，不改轮次终态。
- 抽取输入只有最近3个同会话、本人、已完成轮次（遗忘边界之后、不含回答选择卡的轮次）的`user_text`与助手最终回复，加当前active事实快照；绝不输入工具结果、网页或攻略。模型走ADR-011同一无工具固定温度路径（`structured_call("memory")`），规则在`persona.MEMORY_EXTRACTOR`。
- 输出逐条进入`MemoryService.propose_with_deferred(extracted=True)`：来源轮必须completed且未早于`memory_forgotten_at`；quote按原规则（NFKC去空白≥4字或整条短回复）核验，来源从“本轮”扩展为上述最近3轮的用户原话。同一引用已有提议/已拒绝时静默跳过，不重复出卡；规划中暂缓与草稿后合并卡逻辑不变。一条不合法只丢这一条并计入invalid。
- 并发：同会话抽取串行（进程内锁）；记忆确认卡本就不受旅行revision约束，用户已发下一轮时照常提出。真实模型调用共用`live.exclusive`进程互斥锁（非阻塞，占用即失败），所以新的真实模型轮次开始前先等进行中的抽取结束（最多90秒），不让用户下一轮因锁被占直接失败；反过来抽取遇到锁被占则本轮放弃（记日志），不重试。
- 确认卡送达：卡片作为来源轮的`presentation`事件追加（`tool_name=memory_extractor`），`RunView.memory_pending`在抽取进行中为true（终态提交前登记，读到completed必同时看到pending）。前端在终态后按`memory_pending`低频轮询`/runs/{id}`补卡（3秒一次、最多约2分钟）；刷新/历史通过`presentations`恢复（记忆卡单独取，不挤掉本轮最后4个展示）。
- 评测：v3直播与v2-memory在轮次结束后同步等待/调用同一抽取器；L1仍按`source_run_id`查事实，被拒提议按`memory_extractor`的`validation`事件计invalid。

## 后果

- 本轮回复不再被记忆调用拖慢；记忆卡比回复晚出现几秒到几十秒（一次DeepSeek无工具调用）。用户在抽取结束前就发下一条时，下一轮要先等抽取结束。
- 同轮暂存草稿的情况下，原来“暂缓后与表单答案合并成一组卡”变为：表单答案合并卡在暂存时出，抽取到的偏好随后单独出卡。
- 每个真实模型轮次多一次小模型调用（按ADR-004同一预算守卫计费）。
- `services.memory_extractor`对`providers.claude_agent.structured`的懒导入登记为分层债务（构造参数已可注入）。
- v2-memory（历史集）里trip/否定/第三方等早于2026-10-19“只有四项可长期记住”决定的期望，可能与新抽取规则不一致；现行v3集已按新规则。
