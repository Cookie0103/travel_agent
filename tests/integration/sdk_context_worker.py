"""SDK 集成测试子进程。需要测试压缩时，先生成可压缩的历史再执行业务。"""

import os
from collections.abc import AsyncIterable
from contextlib import nullcontext
from typing import Any
from unittest.mock import patch

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    SystemMessage,
    ToolUseBlock,
)

from backend.providers.claude_agent import runtime, worker
from backend.providers.claude_agent.runtime import outcome_from_result
from tests.support.clock import fixture_travel_calendar


class HistoryClient(ClaudeSDKClient):
    async def query(
        self, prompt: str | AsyncIterable[dict[str, Any]], session_id: str = "default"
    ) -> None:
        for index in range(2):
            await super().query(f"offline-history-warmup-{index}", session_id)
            completed = False
            async for message in self.receive_response():
                if isinstance(message, AssistantMessage) and any(
                    isinstance(block, ToolUseBlock) for block in message.content
                ):
                    raise RuntimeError("warmup cannot call tools")
                if isinstance(message, SystemMessage) and message.subtype == "compact_boundary":
                    raise RuntimeError("warmup must not compact")
                if isinstance(message, ResultMessage):
                    if outcome_from_result(message).code is not None:
                        raise RuntimeError("warmup did not complete")
                    completed = True
            if not completed:
                raise RuntimeError("warmup missing terminal result")
        await super().query(prompt, session_id)


if __name__ == "__main__":
    history = (
        patch.object(runtime, "ClaudeSDKClient", HistoryClient)
        if "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE" in os.environ
        else nullcontext()
    )
    with fixture_travel_calendar(), history:
        worker.main()
