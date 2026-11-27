"""Claude Agent SDK：工具走进程内MCP；output_format=JSON Schema；底层是 Claude Code CLI 子进程。"""

import shutil
import tempfile

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    SdkMcpTool,
    create_sdk_mcp_server,
)

from bench.common import API_KEY, MAX_MODEL_CALLS, MODEL, SYSTEM_PROMPT, Case, RunCtx, RunOutput
from bench.tools import ItineraryDraft, Tool, json_schema, make_tools, tool_doc


def _mcp_tool(fn: Tool) -> SdkMcpTool:
    async def handler(args: dict) -> dict:
        return {"content": [{"type": "text", "text": await fn(**args)}]}

    return SdkMcpTool(fn.__name__, tool_doc(fn), json_schema(fn), handler)


def _options(case: Case, ctx: RunCtx, cwd: str) -> ClaudeAgentOptions:
    tools = make_tools(ctx.env, case.tools)
    bash = shutil.which("bash")
    # 原生结构化输出只做JSON Schema校验，业务规则（Itinerary的validator）无法表达在schema里
    output = {"type": "json_schema", "schema": ItineraryDraft.model_json_schema()}
    return ClaudeAgentOptions(
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        tools=[],  # 关掉Claude Code内置的Bash/Read/Edit等
        allowed_tools=[f"mcp__travel__{fn.__name__}" for fn in tools],
        mcp_servers={
            "travel": create_sdk_mcp_server("travel", tools=[_mcp_tool(fn) for fn in tools])
        },
        strict_mcp_config=True,
        setting_sources=[],
        permission_mode="dontAsk",
        max_turns=MAX_MODEL_CALLS,
        thinking={"type": "disabled"},
        output_format=output if case.output else None,
        cwd=cwd,
        extra_args={"no-session-persistence": None},
        env={
            "ANTHROPIC_BASE_URL": ctx.anthropic_base,
            "ANTHROPIC_AUTH_TOKEN": API_KEY,
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_SMALL_FAST_MODEL": MODEL,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": MODEL,
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_TELEMETRY": "1",
            "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            **({"CLAUDE_CODE_GIT_BASH_PATH": bash} if bash else {}),
        },
    )


async def run(case: Case, ctx: RunCtx) -> RunOutput:
    out = RunOutput()
    with tempfile.TemporaryDirectory() as cwd:  # 空目录，避免CLAUDE.md等上下文混入
        async with ClaudeSDKClient(_options(case, ctx, cwd)) as client:
            await client.query(case.prompt)
            async for msg in client.receive_response():
                if isinstance(msg, ResultMessage):
                    if msg.is_error:
                        raise RuntimeError(f"{msg.subtype}: {msg.result or msg.errors}")
                    out.text, out.structured = msg.result or "", msg.structured_output
    return out
