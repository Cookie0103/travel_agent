"""R01：MCP 只桥接现有执行器，身份来自服务端，异常正文不会传给模型。"""

import json
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext, RuntimeEvent
from backend.mcp.bridge import _build_tool, build_server
from backend.tools.contracts import ToolDefinition, ToolResult

DEFINITION = ToolDefinition("search_places", "search", {"type": "object"})


class RecordingExecutor:
    def __init__(self, fail: bool) -> None:
        self.fail = fail
        self.context: RunContext | None = None

    async def execute(
        self, context: RunContext, name: str, arguments: dict[str, object]
    ) -> ToolResult:
        self.context = context
        if self.fail:
            raise RuntimeError("downstream-secret")
        return ToolResult({"places": []})


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_bridge_keeps_identity_and_sanitizes_errors(fail: bool) -> None:
    executor = RecordingExecutor(fail)
    context = RunContext(uuid4())
    events: list[RuntimeEvent] = []
    registered = _build_tool(DEFINITION, executor, context, events.append)
    result = await registered.handler({"user_id": "forged"})
    assert executor.context == context and result["is_error"] == fail
    assert "downstream-secret" not in str(result)
    assert [e.kind for e in events] == ["tool_started", "tool_finished"]
    assert events[-1].code == ("unavailable" if fail else None)


def test_duplicate_tools_are_rejected_before_sdk_registration() -> None:
    with pytest.raises(ValueError, match="重复"):
        build_server(
            (DEFINITION, DEFINITION), RecordingExecutor(False), RunContext(uuid4()), lambda e: None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_event", ["tool_started", "tool_finished"])
async def test_event_sink_exception_is_not_exposed_to_sdk(failing_event: str) -> None:
    def emit(event: RuntimeEvent) -> None:
        if event.kind == failing_event:
            raise RuntimeError("private-sink-secret")

    executor = RecordingExecutor(False)
    registered = _build_tool(DEFINITION, executor, RunContext(uuid4()), emit)
    result = await registered.handler({})
    assert result["is_error"] is True
    assert "private-sink-secret" not in str(result) and "unavailable" in str(result)
    assert (executor.context is None) == (failing_event == "tool_started")


STAGE = ToolDefinition("stage_plan_change", "stage", {"type": "object"}, kind="draft")


class Committed:
    """写工具已提交：返回含超大/不可序列化内容的结果。"""

    def __init__(self, extra: object) -> None:
        self.extra, self.calls = extra, 0

    async def execute(
        self, context: RunContext, name: str, arguments: dict[str, object]
    ) -> ToolResult:
        self.calls += 1
        return ToolResult(
            {"draft_id": "d-1", "plan_id": "p-1", "huge": self.extra, "request_revision": 3},
            evidence_ids=("e-1",),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["sink", "serialization"])
async def test_write_committed_before_display_failure_is_never_reported_as_not_happened(
    failure: str,
) -> None:
    def emit(event: RuntimeEvent) -> None:
        if failure == "sink" and event.kind == "tool_finished":
            raise RuntimeError("private-sink-secret")

    executor = Committed(object() if failure == "serialization" else "x" * 100)
    registered = _build_tool(STAGE, executor, RunContext(uuid4()), emit)
    result = await registered.handler({})
    body = json.loads(result["content"][0]["text"])
    assert result["is_error"] is False and body["status"] == "ok"
    assert body["data"] == {"draft_id": "d-1", "plan_id": "p-1", "request_revision": 3}
    assert body["evidence_ids"] == ["e-1"]
    assert "已提交" in body["warnings"][0] and "不要重复" in body["warnings"][0]
    assert "private-sink-secret" not in str(result) and executor.calls == 1


@pytest.mark.asyncio
async def test_write_that_never_ran_or_read_tool_failure_still_reports_unavailable() -> None:
    def emit(event: RuntimeEvent) -> None:
        if event.kind == "tool_started":
            raise RuntimeError("boom")

    executor = Committed("x")
    registered = _build_tool(STAGE, executor, RunContext(uuid4()), emit)
    result = await registered.handler({})
    assert result["is_error"] is True and executor.calls == 0
