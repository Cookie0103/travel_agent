"""R12/R17：实际PG事件导出与写盘故障隔离，不以Trace替代业务事实。"""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from backend.agent.runtime import EventSink, FakeRuntime
from backend.domain.execution import RunContext, RuntimeOutcome
from backend.services.runs import MessageInput, RunService
from backend.services.travel import TravelService
from backend.tools.contracts import ToolExecutor
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


class PatchRuntime(FakeRuntime):
    def __init__(self, executor: ToolExecutor) -> None:
        super().__init__(RuntimeOutcome())
        self.executor = executor

    async def execute(
        self,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        result = await execute_observed(
            self.executor,
            context,
            "update_travel_request",
            {"expected_revision": 1, "set": {"interests": [prompt]}},
            emit,
            definition=next(d for d in DEFINITIONS if d.name == "update_travel_request"),
        )
        return RuntimeOutcome(text=prompt, sdk_session_id="fixture", code=result.code)


@pytest.mark.parametrize("disk_failure", [False, True])
def test_committed_run_exports_metadata_or_preserves_result_on_disk_failure(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    disk_failure: bool,
) -> None:
    runner, travel, context = travel_setup
    directory = tmp_path / "traces"
    if disk_failure:
        directory.write_text("blocked", encoding="utf-8")
    service = RunService(travel.database, runtime_factory=PatchRuntime, trace_directory=directory)
    private_text = "私人喜好，不能出现在Trace全文中"

    async def exercise() -> None:
        created = await service.submit(
            context.user_id,
            context.session_id,
            MessageInput(client_message_id=uuid4(), text=private_text),
        )
        await asyncio.gather(*tuple(service.tasks.values()))
        final = await service.get(context.user_id, created.run_id)
        assert final.status == "completed" and final.answer == private_text
        assert (await travel.get_request(context)).revision == 2
        assert not service.tasks and not service.persistence_failures
        path = (
            directory / str(context.user_id) / str(context.session_id) / f"{created.run_id}.jsonl"
        )
        if disk_failure:
            assert "TaskRun Trace unavailable" in caplog.text
            assert private_text not in caplog.text
            return
        raw = path.read_text(encoding="utf-8")
        assert private_text not in raw
        spans = [json.loads(line) for line in raw.splitlines()]
        root = next(s for s in spans if s["name"] == "travel.run")
        tool = next(s for s in spans if s["name"] == "tool.update_travel_request")
        assert root["attributes"]["travel.run_id"] == str(created.run_id)
        assert root["attributes"]["travel.status"] == "completed"
        assert tool["attributes"]["travel.request_revision"] == 2
        assert tool["attributes"]["tool.argument_keys"] == ["expected_revision", "set"]
        assert tool["attributes"]["tool.status"] == "ok"
        events = await service.events(context.user_id, created.run_id, 0)
        assert events[-1]["kind"] == "completed"
        assert [e["sequence"] for e in events] == [1, 2, 3, 4]

    runner.run(exercise())
