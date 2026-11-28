"""Pydantic AI：类型化函数直接当工具；output_type=Pydantic模型，校验失败自动把错误回给模型重试。"""

from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

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


async def run(case: Case, ctx: RunCtx, force_tool: bool = False) -> RunOutput:
    tools = make_tools(ctx.env, case.tools)
    settings = ModelSettings(extra_body=NO_THINKING)
    if (
        force_tool
    ):  # 消融实验：像LangChain ToolStrategy一样每轮强制调用工具（含输出工具final_result）
        settings["tool_choice"] = [fn.__name__ for fn in tools] + ["final_result"]
        settings["thinking"] = False  # 让Pydantic AI知道思考已关闭，否则它会拒绝强制工具调用
    client = AsyncOpenAI(api_key=API_KEY, base_url=ctx.openai_base)
    agent = Agent(
        OpenAIChatModel(MODEL, provider=DeepSeekProvider(openai_client=client)),
        instructions=SYSTEM_PROMPT,
        tools=tools,
        output_type=case.output or str,
        retries={"tools": 1, "output": 3},  # 输出校验重试默认1次，与其他SDK对齐给3次
        model_settings=settings,
    )
    limits = UsageLimits(request_limit=MAX_MODEL_CALLS)
    result = await agent.run(case.prompt, usage_limits=limits)
    if case.output:
        return RunOutput(structured=result.output.model_dump())
    return RunOutput(text=result.output)
