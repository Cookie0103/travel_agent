"""真实PG：trace锚点在消息事务创建，运行结束的OTel复用它。"""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext
from backend.persistence.models import TaskRunRow
from backend.services.runs import MessageInput, RunService
from backend.services.travel import TravelService
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


def test_message_transaction_creates_stable_trace_anchor(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    tmp_path: Path,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        service = RunService(travel.database, trace_directory=tmp_path)
        message = MessageInput(client_message_id=uuid4(), text="合成问候")
        run = await service.submit(context.user_id, context.session_id, message)
        assert (
            await service.submit(context.user_id, context.session_id, message)
        ).run_id == run.run_id
        await asyncio.gather(*tuple(service.tasks.values()))
        async with travel.database.sessions() as db:
            row = await db.get(TaskRunRow, run.run_id)
            assert row and row.trace_id and len(row.trace_id) == 32
            anchor = row.trace_id
        traces = list(tmp_path.rglob("*.jsonl"))
        assert len(traces) == 1
        spans = [json.loads(line) for line in traces[0].read_text().splitlines()]
        assert all(span["context"]["trace_id"] == "0x" + anchor for span in spans)

    runner.run(exercise())
