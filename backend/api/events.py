"""SSE只读取已提交的应用事件；断线不会取消或重新启动Agent。"""

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import Request

from backend.services.runs import RunService


async def stream_events(
    request: Request, service: RunService, user_id: UUID, run_id: UUID, after: int
) -> AsyncIterator[str]:
    while not await request.is_disconnected():
        events = await service.events(user_id, run_id, after)
        for event in events:
            sequence = event["sequence"]
            assert isinstance(sequence, int)
            after = sequence
            payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            yield f"id: {after}\ndata: {payload}\n\n"
        current = await service.get(user_id, run_id)
        if current.status not in {"running", "cancelling"} and after >= current.last_sequence:
            return
        if not events:
            yield ": waiting\n\n"
            await asyncio.sleep(0.25)
