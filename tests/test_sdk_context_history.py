"""压缩历史夹具仍要求 SDK 成功终态，不吞掉边界/失败。"""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from claude_agent_sdk import ClaudeSDKClient, Message, ResultMessage, SystemMessage

from tests.integration.sdk_context_worker import HistoryClient
from tests.integration.sdk_helper import CompactionHistory


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["aborted_streaming", "future", "compact_boundary"])
async def test_warmup_boundary_or_invalid_terminal_stops_before_business_prompt(
    monkeypatch: pytest.MonkeyPatch, stop: str
) -> None:
    sent: list[str] = []

    async def query(self: ClaudeSDKClient, prompt: str, session_id: str = "default") -> None:
        sent.append(prompt)

    async def receive(self: ClaudeSDKClient) -> AsyncIterator[Message]:
        if stop == "compact_boundary":
            yield SystemMessage("compact_boundary", {})
        yield ResultMessage("success", 1, 1, False, 1, "sdk", result="done", terminal_reason=stop)

    monkeypatch.setattr(ClaudeSDKClient, "query", query)
    monkeypatch.setattr(ClaudeSDKClient, "receive_response", receive)
    with pytest.raises(RuntimeError):
        await HistoryClient().query("business prompt")
    assert sent == ["offline-history-warmup-0"]


@pytest.mark.parametrize("kind,code", [("tool_started", None), ("tool_finished", "unavailable")])
def test_summary_refuses_history_without_prior_successful_business_tool(
    tmp_path: Path, kind: str, code: str | None
) -> None:
    def unused(body: bytes) -> tuple[int, bytes]:
        raise AssertionError("summary must not invoke normal business response")

    history = CompactionHistory(unused)
    history.warmups = [{}, {}]
    history.business = [{}]
    history.event_path = tmp_path / "events.jsonl"
    history.event_path.write_text(
        json.dumps({"kind": kind, "tool_name": "load_skill", "code": code})
    )
    body = json.dumps(
        {"messages": [{"role": "user", "content": "REMINDER: Do NOT call any tools. <summary>"}]}
    ).encode()
    with pytest.raises(AssertionError, match="successful business tool"):
        history(body)
