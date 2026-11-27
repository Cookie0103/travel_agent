## 通过次数（模型 deepseek-flash）

| SDK | E1a_api_503x2 | E1b_api_429x4 | E1c_tool_error | E2a_native_output | E2b_validate_tool | E3_parallel |
|---|---|---|---|---|---|---|
| pydantic_ai | 5/5 | 0/5 | 0/5 | 8/8 | 8/8 | 5/5 |
| openai_agents | 5/5 | 0/5 | 5/5 | 0/8 | 7/8 | 5/5 |
| langchain | 5/5 | 0/5 | 0/5 | 2/8 | 8/8 | 5/5 |
| claude_agent_sdk | 5/5 | 5/5 | 5/5 | 8/8 | 8/8 | 5/5 |
| pi | 0/5 | 0/5 | 5/5 | 不支持 | 8/8 | 5/5 |
| pydantic_ai+forced_tool | — | — | — | 1/8 | — | — |

## E1a_api_503x2

| SDK | 通过 | 中位耗时s | 平均模型请求 | 平均输入token | 平均输出token | 平均成本¥ | 工具并发峰值 |
|---|---|---|---|---|---|---|---|
| pydantic_ai | 5/5 | 4.9 | 4.0 | 1526 | 235 | 0.0049 | 1 |
| openai_agents | 5/5 | 4.3 | 4.0 | 1465 | 238 | 0.0048 | 1 |
| langchain | 5/5 | 4.8 | 4.0 | 1387 | 217 | 0.0045 | 1 |
| claude_agent_sdk | 5/5 | 5.5 | 4.0 | 1923 | 337 | 0.0065 | 1 |
| pi | 0/5 | 0.5 | 1.0 | 0 | 0 | 0.0000 | 0 |

## E1b_api_429x4

| SDK | 通过 | 中位耗时s | 平均模型请求 | 平均输入token | 平均输出token | 平均成本¥ | 工具并发峰值 |
|---|---|---|---|---|---|---|---|
| pydantic_ai | 0/5 | 2.1 | 3.0 | 0 | 0 | 0.0000 | 0 |
| openai_agents | 0/5 | 2.0 | 3.0 | 0 | 0 | 0.0000 | 0 |
| langchain | 0/5 | 2.0 | 3.0 | 0 | 0 | 0.0000 | 0 |
| claude_agent_sdk | 5/5 | 12.6 | 6.0 | 1924 | 360 | 0.0067 | 1 |
| pi | 0/5 | 1.0 | 1.0 | 0 | 0 | 0.0000 | 0 |

## E1c_tool_error

| SDK | 通过 | 中位耗时s | 平均模型请求 | 平均输入token | 平均输出token | 平均成本¥ | 工具并发峰值 |
|---|---|---|---|---|---|---|---|
| pydantic_ai | 0/5 | 1.2 | 1.0 | 528 | 99 | 0.0018 | 1 |
| openai_agents | 5/5 | 3.5 | 3.0 | 2200 | 334 | 0.0071 | 1 |
| langchain | 0/5 | 1.2 | 1.0 | 455 | 103 | 0.0017 | 1 |
| claude_agent_sdk | 5/5 | 4.6 | 3.0 | 2951 | 524 | 0.0101 | 1 |
| pi | 5/5 | 5.1 | 3.0 | 2187 | 417 | 0.0077 | 1 |

## E2a_native_output

| SDK | 通过 | 中位耗时s | 平均模型请求 | 平均输入token | 平均输出token | 平均成本¥ | 工具并发峰值 |
|---|---|---|---|---|---|---|---|
| pydantic_ai | 8/8 | 12.1 | 5.2 | 14257 | 2694 | 0.0501 | 20 |
| openai_agents | 0/8 | 0.2 | 1.0 | 0 | 0 | 0.0000 | 0 |
| langchain | 2/8 | 48.0 | 25.2 | 182110 | 5823 | 0.4108 | 8 |
| claude_agent_sdk | 8/8 | 12.1 | 3.5 | 8238 | 2774 | 0.0387 | 1 |
| pi | 不支持 | | | | | | |
| pydantic_ai+forced_tool | 1/8 | 19.1 | 13.0 | 62079 | 3747 | 0.1541 | 16 |

## E2b_validate_tool

| SDK | 通过 | 中位耗时s | 平均模型请求 | 平均输入token | 平均输出token | 平均成本¥ | 工具并发峰值 |
|---|---|---|---|---|---|---|---|
| pydantic_ai | 8/8 | 15.0 | 6.2 | 17007 | 2773 | 0.0562 | 16 |
| openai_agents | 7/8 | 16.8 | 6.9 | 20292 | 2922 | 0.0640 | 8 |
| langchain | 8/8 | 15.2 | 7.1 | 20483 | 3037 | 0.0653 | 10 |
| claude_agent_sdk | 8/8 | 15.6 | 4.6 | 12901 | 2972 | 0.0496 | 1 |
| pi | 8/8 | 12.2 | 6.0 | 15576 | 2340 | 0.0499 | 5 |

## E3_parallel

| SDK | 通过 | 中位耗时s | 平均模型请求 | 平均输入token | 平均输出token | 平均成本¥ | 工具并发峰值 |
|---|---|---|---|---|---|---|---|
| pydantic_ai | 5/5 | 4.5 | 2.0 | 1158 | 279 | 0.0046 | 4 |
| openai_agents | 5/5 | 5.0 | 2.0 | 1056 | 295 | 0.0045 | 4 |
| langchain | 5/5 | 4.5 | 2.0 | 1015 | 294 | 0.0044 | 4 |
| claude_agent_sdk | 5/5 | 12.2 | 2.0 | 1544 | 362 | 0.0060 | 1 |
| pi | 5/5 | 5.8 | 2.0 | 1033 | 297 | 0.0044 | 4 |

## 失败明细

- pi E1a_api_503x2#0: CRASH RuntimeError: if (last?.stopReason === "error") throw new Error(last.errorMessage ?? "model error");
- pi E1a_api_503x2#1: CRASH RuntimeError: if (last?.stopReason === "error") throw new Error(last.errorMessage ?? "model error");
- pi E1a_api_503x2#2: CRASH RuntimeError: if (last?.stopReason === "error") throw new Error(last.errorMessage ?? "model error");
- pi E1a_api_503x2#3: CRASH RuntimeError: if (last?.stopReason === "error") throw new Error(last.errorMessage ?? "model error");
- pi E1a_api_503x2#4: CRASH RuntimeError: if (last?.stopReason === "error") throw new Error(last.errorMessage ?? "model error");
- pydantic_ai E1b_api_429x4#0: CRASH ModelRateLimitError: status_code: 429, model_name: deepseek-flash, body: {'message': 'injected fault'}
- pydantic_ai E1b_api_429x4#1: CRASH ModelRateLimitError: status_code: 429, model_name: deepseek-flash, body: {'message': 'injected fault'}
- pydantic_ai E1b_api_429x4#2: CRASH ModelRateLimitError: status_code: 429, model_name: deepseek-flash, body: {'message': 'injected fault'}
- pydantic_ai E1b_api_429x4#3: CRASH ModelRateLimitError: status_code: 429, model_name: deepseek-flash, body: {'message': 'injected fault'}
- pydantic_ai E1b_api_429x4#4: CRASH ModelRateLimitError: status_code: 429, model_name: deepseek-flash, body: {'message': 'injected fault'}
- openai_agents E1b_api_429x4#0: CRASH RateLimitError: Error code: 429 - injected fault
- openai_agents E1b_api_429x4#1: CRASH RateLimitError: Error code: 429 - injected fault
- openai_agents E1b_api_429x4#2: CRASH RateLimitError: Error code: 429 - injected fault
- openai_agents E1b_api_429x4#3: CRASH RateLimitError: Error code: 429 - injected fault
- openai_agents E1b_api_429x4#4: CRASH RateLimitError: Error code: 429 - injected fault
- langchain E1b_api_429x4#0: CRASH OpenAIRateLimitError: Error code: 429 - injected fault
- langchain E1b_api_429x4#1: CRASH OpenAIRateLimitError: Error code: 429 - injected fault
- langchain E1b_api_429x4#2: CRASH OpenAIRateLimitError: Error code: 429 - injected fault
- langchain E1b_api_429x4#3: CRASH OpenAIRateLimitError: Error code: 429 - injected fault
- langchain E1b_api_429x4#4: CRASH OpenAIRateLimitError: Error code: 429 - injected fault
- pi E1b_api_429x4#0: CRASH RuntimeError: if (last?.stopReason === "error") throw new Error(last.errorMessage ?? "model error");
- pi E1b_api_429x4#1: CRASH RuntimeError: if (last?.stopReason === "error") throw new Error(last.errorMessage ?? "model error");
- pi E1b_api_429x4#2: CRASH RuntimeError: if (last?.stopReason === "error") throw new Error(last.errorMessage ?? "model error");
- pi E1b_api_429x4#3: CRASH RuntimeError: if (last?.stopReason === "error") throw new Error(last.errorMessage ?? "model error");
- pi E1b_api_429x4#4: CRASH RuntimeError: if (last?.stopReason === "error") throw new Error(last.errorMessage ?? "model error");
- pydantic_ai E1c_tool_error#0: CRASH ToolError: UPSTREAM_TIMEOUT: 供应商接口超时，请稍后重试同一请求
- pydantic_ai E1c_tool_error#1: CRASH ToolError: UPSTREAM_TIMEOUT: 供应商接口超时，请稍后重试同一请求
- pydantic_ai E1c_tool_error#2: CRASH ToolError: UPSTREAM_TIMEOUT: 供应商接口超时，请稍后重试同一请求
- pydantic_ai E1c_tool_error#3: CRASH ToolError: UPSTREAM_TIMEOUT: 供应商接口超时，请稍后重试同一请求
- pydantic_ai E1c_tool_error#4: CRASH ToolError: UPSTREAM_TIMEOUT: 供应商接口超时，请稍后重试同一请求
- langchain E1c_tool_error#0: CRASH ToolError: UPSTREAM_TIMEOUT: 供应商接口超时，请稍后重试同一请求
- langchain E1c_tool_error#1: CRASH ToolError: UPSTREAM_TIMEOUT: 供应商接口超时，请稍后重试同一请求
- langchain E1c_tool_error#2: CRASH ToolError: UPSTREAM_TIMEOUT: 供应商接口超时，请稍后重试同一请求
- langchain E1c_tool_error#3: CRASH ToolError: UPSTREAM_TIMEOUT: 供应商接口超时，请稍后重试同一请求
- langchain E1c_tool_error#4: CRASH ToolError: UPSTREAM_TIMEOUT: 供应商接口超时，请稍后重试同一请求
- openai_agents E2a_native_output#0: CRASH BadRequestError: Error code: 400 - This response_format type is unavailable now (request_id: c59392ea-a315-4350-81d0-9f366b5aa469)
- openai_agents E2a_native_output#1: CRASH BadRequestError: Error code: 400 - This response_format type is unavailable now (request_id: 7c0d4e0b-42c6-408c-9a0e-3339a59bcad0)
- openai_agents E2a_native_output#2: CRASH BadRequestError: Error code: 400 - This response_format type is unavailable now (request_id: cf555d45-f632-46da-9b87-7a150320479c)
- openai_agents E2a_native_output#3: CRASH BadRequestError: Error code: 400 - This response_format type is unavailable now (request_id: 77dd1c66-ee26-4e4b-a65b-bed8b81d9c6a)
- openai_agents E2a_native_output#4: CRASH BadRequestError: Error code: 400 - This response_format type is unavailable now (request_id: 69800fcb-5bb9-4083-803d-8609c135348d)
- openai_agents E2a_native_output#5: CRASH BadRequestError: Error code: 400 - This response_format type is unavailable now (request_id: 1f0c3bcf-443e-4f7a-863a-599b0780c576)
- openai_agents E2a_native_output#6: CRASH BadRequestError: Error code: 400 - This response_format type is unavailable now (request_id: 46d59135-a610-42ae-a94a-519f1a58b4c1)
- openai_agents E2a_native_output#7: CRASH BadRequestError: Error code: 400 - This response_format type is unavailable now (request_id: a2c96b81-297b-4684-a50a-3fcf644b4539)
- langchain E2a_native_output#0: CRASH GraphRecursionError: Recursion limit of 41 reached without hitting a stop condition. You can increase the limit by setting the `recursion_limit` config key.
For troubleshooting, visit: https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT
- langchain E2a_native_output#1: CRASH GraphRecursionError: Recursion limit of 41 reached without hitting a stop condition. You can increase the limit by setting the `recursion_limit` config key.
For troubleshooting, visit: https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT
- langchain E2a_native_output#2: CRASH GraphRecursionError: Recursion limit of 41 reached without hitting a stop condition. You can increase the limit by setting the `recursion_limit` config key.
For troubleshooting, visit: https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT
- langchain E2a_native_output#3: CRASH GraphRecursionError: Recursion limit of 41 reached without hitting a stop condition. You can increase the limit by setting the `recursion_limit` config key.
For troubleshooting, visit: https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT
- langchain E2a_native_output#4: CRASH GraphRecursionError: Recursion limit of 41 reached without hitting a stop condition. You can increase the limit by setting the `recursion_limit` config key.
For troubleshooting, visit: https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT
- langchain E2a_native_output#6: CRASH GraphRecursionError: Recursion limit of 41 reached without hitting a stop condition. You can increase the limit by setting the `recursion_limit` config key.
For troubleshooting, visit: https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT
- pydantic_ai+forced_tool E2a_native_output#1: CRASH UnexpectedModelBehavior: Exceeded maximum output retries (3)
- pydantic_ai+forced_tool E2a_native_output#2: CRASH UnexpectedModelBehavior: Exceeded maximum output retries (3)
- pydantic_ai+forced_tool E2a_native_output#3: CRASH UnexpectedModelBehavior: Exceeded maximum output retries (3)
- pydantic_ai+forced_tool E2a_native_output#4: CRASH UnexpectedModelBehavior: Exceeded maximum output retries (3)
- pydantic_ai+forced_tool E2a_native_output#5: CRASH UsageLimitExceeded: The next request would exceed the request_limit of 20. Consider raising the limit, or see the docs on usage limits for budget-aware patterns: https://pydantic.dev/docs/ai/core-concepts/agent/#usage-limits
- pydantic_ai+forced_tool E2a_native_output#6: CRASH UnexpectedModelBehavior: Exceeded maximum output retries (3)
- pydantic_ai+forced_tool E2a_native_output#7: CRASH UsageLimitExceeded: The next request would exceed the request_limit of 20. Consider raising the limit, or see the docs on usage limits for budget-aware patterns: https://pydantic.dev/docs/ai/core-concepts/agent/#usage-limits
- openai_agents E2b_validate_tool#1: 没有调用validate_itinerary
