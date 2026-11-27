# Agent SDK 选型实测：同一模型、同一工具，SDK 到底在哪里造成差异

独立调研，不影响 travel-agent 主链（不改 `backend`，不改主项目依赖）。

## 0. 一句话结论

在简单任务上，这 5 个 SDK 没有区别。差异出现在三个地方：

- **出故障时的默认行为**：决定下限。
- **结构化输出的实现方式**：决定上限。
- **工具是并行还是串行执行**：决定延迟。

它们都是 SDK 自己的设计选择，不是"少写了一行代码"。另外，"让模型先校验再提交"这个设计（E2b）能把 5 个 SDK 拉回到同一水平。所以 SDK 定的是默认的下限和起点，设计概念定的是上限。

## 1. 被测 SDK（2026-11）

| SDK | 版本 | 语言 | 工具注册方式（全部用官方惯用写法） |
|---|---|---|---|
| Pydantic AI | 2.66 | Py | 带类型注解的函数直接传入 `tools=[...]` |
| OpenAI Agents SDK | 0.24 | Py | `@function_tool` |
| LangChain v1 `create_agent`（运行在 LangGraph 上） | langchain 1.x / langgraph 1.2 | Py | `@tool` |
| Claude Agent SDK | 0.2.178（CLI 2.1.318） | Py | 进程内 MCP 工具 |
| pi（`@earendil-works/pi-agent-core`） | 1.5 | TS | `AgentTool`，抛错即视为工具失败 |

## 2. 怎么测

**只让 SDK 这一个变量变化：**

- **模型**：全部用 DeepSeek `deepseek-flash`，关闭思考模式。
- **工具**：同一份 Python 实现。pi 是 TS，通过本地 HTTP 回调同一份实现。
- **提示词**：同一段 system prompt。
- **步数预算**：统一最多 20 次模型请求。这是资源上限，不算行为差异。
- **不加补丁**：每个 SDK 都用它官方文档的写法，不额外写错误处理或重试。

**统一计量（`bench/proxy.py`）：** 所有 SDK 的模型请求都经过同一个本地代理再转发到 DeepSeek。token、请求次数、故障注入都在代理层统一完成，不依赖各 SDK 自己报告的数字。代理还能保存请求体，用来看 SDK 实际发给模型的内容。

**评分（`bench/tasks.py`）：** 确定性评分，不用 LLM 裁判。行程类任务用同一个业务校验器检查营业时间、交通时间、门票和必去景点。

| 实验 | 考察什么 | 场景 |
|---|---|---|
| **E1 下限：故障** | SDK 原生默认行为能不能兜住故障 | 查最便宜的酒店。E1a：前 2 次模型请求返回 503。E1b：前 4 次返回 429。E1c：工具第一次调用抛超时异常 |
| **E2 上限：复杂结构化输出** | SDK 原生的结构化输出机制能不能产出合格结果 | 排 7 个景点的一日游：3 个必去点、营业时间、闭馆日、交通时间、门票预算 2000 日元。第一稿约 30~40% 不合格（小样本预跑估算）。E2a：用 SDK 原生结构化输出，把带业务校验的 Pydantic 模型交给它。E2b：所有 SDK 都改成"先调用 `validate_itinerary` 校验、不合格就修改"（设计概念层面的做法） |
| **E3 延迟：并行工具** | 模型一次发出多个工具调用时，SDK 是否并行执行 | 比较 4 个日期的房价，每次查询固定耗时 2 秒 |

## 3. 结果（`results/final-summary.md`，E1/E3 每格 5 次，E2 每格 8 次）

| SDK | E1a 503×2 | E1b 429×4 | E1c 工具异常 | E2a 原生结构化 | E2b 校验工具 | E3 耗时 / 并发峰值 |
|---|---|---|---|---|---|---|
| Pydantic AI | 5/5 | **0/5** | **0/5** | **8/8** ¥0.050 | 8/8 | 4.5s / 4 |
| OpenAI Agents | 5/5 | **0/5** | 5/5 | **0/8** 请求被拒 | 7/8 | 5.0s / 4 |
| LangChain | 5/5 | **0/5** | **0/5** | **2/8** ¥0.411 | 8/8 | 4.5s / 4 |
| Claude Agent SDK | 5/5 | **5/5** | 5/5 | **8/8** ¥0.039 | 8/8 | **12.2s / 1** |
| pi | **0/5** | **0/5** | 5/5 | 无此机制 | 8/8 | 5.8s / 4 |
| *消融：Pydantic AI 强制调用工具* | | | | ***1/8*** ¥0.154 | | |

## 4. 每个差异的原因（都有证据）

### E1 下限：同样的故障，默认行为完全不同

| SDK | 模型 API 出错 | 工具抛异常 |
|---|---|---|
| Pydantic AI / OpenAI Agents / LangChain | 底层用 `openai` Python 客户端，默认重试 2 次：2 次 503 能恢复，4 次 429 失败 | Pydantic AI：普通异常直接中止，要改成抛 `ModelRetry`。LangChain：`ToolNode` 默认只把参数校验错误交给模型，业务异常中止。OpenAI：`@function_tool` 默认把异常转成文本交给模型 |
| Claude Agent SDK | CLI 自己重试，最多 10 次，带退避；4 次 429 也扛过去了（12.6s） | MCP 工具报错交给模型 |
| pi | **请求层默认 `maxRetries=0`**（`pi-ai/dist/utils/provider-retry.js`），第一次 503 就失败。这是有意设计：重试交给上层应用 | 抛错即生成 `isError` 结果交给模型 |

**结论：** 换 SDK 等于换了一套故障语义。Claude Agent SDK 的鲁棒性最好，代价是它很重；pi 最轻，代价是重试全要自己写。

### E2 上限：结构化输出的实现方式决定能不能做对

- **OpenAI Agents 0/8**：它的结构化输出用的是 `response_format: json_schema`，DeepSeek 不支持，返回 400 `This response_format type is unavailable now`。**这个 SDK 的原生能力默认对方是 OpenAI 自家的 API**，换模型就失效了。
- **LangChain 2/8，成本是 Pydantic AI 的 8 倍**：抓包发现 `ToolStrategy` 在**每次请求都发 `tool_choice: "required"`**，强制模型必须调用工具。模型因此没法先用文字推算时间，只能直接填 JSON。校验不过就重填，平均 25 次请求还没收敛，最后撞上步数上限。
- **Pydantic AI 8/8**：发的是 `tool_choice: auto` 加 `strict: true`。模型先用 500~1200 字推算时间表，再调用输出工具 `final_result`；校验不过时，把错误作为重试提示交还给模型。
- **消融实验（证明因果）**：同一个 Pydantic AI，**只把 `tool_choice` 改成强制调用工具**，通过率从 8/8 掉到 **1/8**，成本涨到 3 倍，和 LangChain 的表现一致。所以 LangChain 的问题不在校验反馈，而在"每轮强制调用工具"这个设计。
- **Claude Agent SDK 8/8**：它的 `output_format` 只校验 JSON Schema，不跑业务规则，但模型照样都做对了。可能的原因：一是模型能先写文字推理；二是 CLI 默认带 `effort=high`，输出明显更长。样本只有 8 次，不能说它"更聪明"。
- **pi**：`pi-agent-core` 没有结构化输出 API，只能走工具（即 E2b 的做法）。
- **Pydantic AI 的两个额外发现**：
  - 它会往 system 里注入一段自己的提示词（关于 `<system>` 标签的说明）。
  - 它内置了 DeepSeek 的模型画像。当你要求强制工具调用、而它认为思考模式开着时，会直接拒绝（`UserError`），提前拦住已知的不兼容组合。

**E2b 说明了设计概念的作用：** 把"校验"做成一个工具，并要求"校验通过才能定稿"之后，5 个 SDK 都达到 7~8/8，成本也接近（¥0.050~0.065）。travel-agent 主项目的 `validate_itinerary` 用的就是这个思路。

### E3 延迟：Claude Agent SDK 串行执行工具

模型在同一次回复里发出 4 个查询。Pydantic AI、OpenAI Agents、LangChain、pi 都**并行执行**（并发峰值 4，约 4.5~5.8s）。Claude Agent SDK 的 MCP 工具**逐个执行**（并发峰值 1，12.2s）。工具越慢、越多，差距越大。

### 成本

- 在简单任务上，Claude Agent SDK 每次请求的 token 更多：CLI 会注入身份声明、计费头和一个占位工具，并默认 `effort=high`（v1 抓包结果，见第 6 节）。
- 在 E2 这种复杂任务上，**决定成本的是请求次数**，不是单次请求的大小：LangChain 不收敛，成本是 Pydantic AI 的 8 倍；Claude 请求次数最少，反而最便宜。

## 5. 选型时怎么判断

| 问题 | 怎么验证 | 本次结论 |
|---|---|---|
| 换模型或供应商后，原生功能还能用吗？ | 用目标模型跑一遍结构化输出和工具调用 | OpenAI Agents 的结构化输出在 DeepSeek 上不可用 |
| 故障默认怎么处理？ | 在代理层注入 503/429，在工具里注入异常 | 每家都不一样，必须测 |
| SDK 实际发给模型的是什么？ | 抓请求体 | LangChain 强制调用工具；Pydantic AI 和 Claude 都会注入提示词 |
| 工具是并行还是串行？ | 工具里加延迟，统计并发峰值 | Claude Agent SDK 串行 |
| 关键质量靠 SDK 还是靠自己的设计？ | 加上设计层的约束（校验工具）后再比一次 | 加上之后差异基本消失 |

## 6. 第一版（v1）的教训

- 第一版只测了单轮查价、多轮对话等简单任务，所有 SDK 都接近 100%，分不出差异。
- 第一版还把"我补写的错误处理"混进了通过率，造成误读。v2 改为全部使用原生写法，并单独测故障。
- v1 用代理抓到的 Claude Agent SDK 注入内容：
  - 身份句 `You are a Claude agent, built on Anthropic's Claude Agent SDK.`；
  - 计费头；
  - 一个 `DeferredToolPlaceholder` 工具；
  - 工具名加上 `mcp__travel__` 前缀；
  - `output_config.effort=high`；
  - 把工具描述里的全角标点改成半角。

## 7. 运行

```bash
cd research/sdk
uv sync                    # 独立 venv
(cd pi && npm install)     # pi 需要 Node 22+
uv run python -m bench.run --repeat 5 --name mytest                        # 全部 5 个 SDK × 6 个用例
uv run python -m bench.run --sdk langchain pydantic_ai --case E2a_native_output
uv run python -m bench.run --sdk pydantic_ai+forced_tool --case E2a_native_output   # 消融
BENCH_DUMP_DIR=<目录> uv run python -m bench.run ...    # 保存 SDK 实际发出的请求体
BENCH_MODEL=deepseek-v4-pro uv run python -m bench.run  # 换模型
```

读取主项目 `.env` 里的 `DEEPSEEK_API_KEY`。本次全部实验（含调试与消融）总成本不到 ¥10。

```
bench/tools.py      共享工具（酒店、景点、行程校验器）、故障与延迟注入、并发计数
bench/proxy.py      计量与故障注入代理
bench/tasks.py      6 个用例与确定性评分
bench/adapters/     每个 SDK 一个适配器，统一接口 run(case, ctx) -> RunOutput
bench/run.py        执行与汇总
pi/run.mjs          pi 的 TS 端
results/final*      本次正式结果（每次运行的工具调用、失败原因都在 jsonl 里）
```

## 8. 局限

- 只测了一个模型家族（DeepSeek）。比如 OpenAI Agents 结构化输出失败、Claude 注入内容带来的额外成本，换成它们各自的原生模型时不成立。
- 每格 5~8 次，只能看出"0/8 对 8/8"这种量级的差异，看不出几个百分点的差别。
- 没测的维度：长对话的上下文压缩、人工审批的暂停与恢复、断点续跑、流式输出、多 agent 交接。
- 行程数据是调研自建的；酒店数据和计价规则来自主项目。
