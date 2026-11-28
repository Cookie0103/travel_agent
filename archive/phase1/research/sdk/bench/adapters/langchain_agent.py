"""LangChain v1 create_agent（运行在 LangGraph 上）：@tool 注册工具；ToolStrategy 结构化输出。"""

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

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


async def run(case: Case, ctx: RunCtx) -> RunOutput:
    llm = ChatOpenAI(model=MODEL, api_key=API_KEY, base_url=ctx.openai_base, extra_body=NO_THINKING)
    agent = create_agent(
        llm,
        [tool(fn) for fn in make_tools(ctx.env, case.tools)],
        system_prompt=SYSTEM_PROMPT,
        response_format=ToolStrategy(case.output) if case.output else None,
    )
    state = await agent.ainvoke(
        {"messages": [{"role": "user", "content": case.prompt}]},
        {"recursion_limit": MAX_MODEL_CALLS * 2 + 1},  # 一次模型调用+一次工具执行各占1步
    )
    if case.output:
        structured = state.get("structured_response")
        return RunOutput(structured=structured.model_dump() if structured else None)
    return RunOutput(text=state["messages"][-1].content)
