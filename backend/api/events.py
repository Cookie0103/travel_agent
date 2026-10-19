"""SSE只读取已提交的应用事件；断线不会取消或重新启动Agent。"""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import Request

from backend.services.runs import RunService

POLL_MIN, POLL_MAX = 0.25, 1.0  # 空闲轮询间隔：有事件即复位，空闲时指数退避到上限
HEARTBEAT_EVERY = 5.0  # 心跳只为保活代理连接，不必每次轮询都发


async def stream_events(
    request: Request, service: RunService, user_id: UUID, run_id: UUID, after: int
) -> AsyncIterator[str]:
    interval, last_beat = POLL_MIN, float("-inf")
    while not await request.is_disconnected():
        events = await service.events(user_id, run_id, after)
        for event in events:
            sequence = event["sequence"]
            assert isinstance(sequence, int)
            after = sequence
            payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            yield f"id: {after}\ndata: {payload}\n\n"
        running, last_sequence = await service.progress(user_id, run_id)
        if not running and after >= last_sequence:
            return
        if events:
            interval = POLL_MIN
            continue
        if time.monotonic() - last_beat >= HEARTBEAT_EVERY:
            last_beat = time.monotonic()
            yield ": waiting\n\n"
        await asyncio.sleep(interval)
        interval = min(interval * 2, POLL_MAX)
