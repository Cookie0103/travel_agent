"""OpenAI Agents SDK：@function_tool 注册工具；output_type 走原生结构化输出。"""

from agents import (
    Agent,
    ModelSettings,
    OpenAIChatCompletionsModel,
    Runner,
    function_tool,
    set_tracing_disabled,
)
from openai import AsyncOpenAI

from bench.common import (
    API_KEY,
    MAX_MODEL_CALLS,
    MODEL,
    NO_THINKING,
    SYSTEM_PROMPT,
    Case,
    RunCtx,
    RunOutput,
)
from bench.tools import make_tools

set_tracing_disabled(True)  # 默认会把trace上传到OpenAI平台


async def run(case: Case, ctx: RunCtx) -> RunOutput:
    client = AsyncOpenAI(api_key=API_KEY, base_url=ctx.openai_base)
    agent = Agent(
        name="travel",
        instructions=SYSTEM_PROMPT,
        model=OpenAIChatCompletionsModel(MODEL, openai_client=client),
        tools=[function_tool(fn) for fn in make_tools(ctx.env, case.tools)],
        output_type=case.output,
        model_settings=ModelSettings(extra_body=NO_THINKING),
    )
    result = await Runner.run(agent, case.prompt, max_turns=MAX_MODEL_CALLS)
    if case.output:
        return RunOutput(structured=result.final_output.model_dump())
    return RunOutput(text=str(result.final_output))
