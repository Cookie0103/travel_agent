"""A2：SSE 空闲轮询退避、心跳节流、终止判断只用轻量进度查询；补发语义不变。"""

from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import Request

from backend.api import events as sse
from backend.services.runs import RunService


class FakeRequest:
    async def is_disconnected(self) -> bool:
        return False


class FakeService:
    """只提供轻量 progress；旧实现每轮调用的 get 在此不存在，会直接失败。"""

    def __init__(self, idle_rounds: int) -> None:
        self.idle, self.rounds = idle_rounds, 0
        self.afters: list[int] = []

    async def events(self, user_id: UUID, run_id: UUID, after: int) -> list[dict[str, object]]:
        self.afters.append(after)
        return [{"sequence": 1, "kind": "completed"}] if self.rounds == self.idle else []

    async def progress(self, user_id: UUID, run_id: UUID) -> tuple[bool, int]:
        self.rounds += 1
        return self.rounds <= self.idle, int(self.rounds > self.idle)


@pytest.mark.asyncio
async def test_idle_backoff_caps_and_heartbeat_is_throttled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    clock = [0.0]

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(sse, "asyncio", SimpleNamespace(sleep=fake_sleep))
    monkeypatch.setattr(sse, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    service = FakeService(idle_rounds=8)
    chunks = [
        chunk
        async for chunk in sse.stream_events(
            cast(Request, FakeRequest()), cast(RunService, service), uuid4(), uuid4(), 0
        )
    ]
    assert sleeps[:4] == [0.25, 0.5, 1.0, 1.0] and max(sleeps) == 1.0
    beats = [c for c in chunks if c.startswith(":")]
    assert 1 <= len(beats) < len(sleeps)  # 不是每次空轮询都发心跳
    assert chunks[-1].startswith("id: 1\n")
    assert service.afters[0] == 0 and service.afters[-1] == 0  # 游标语义不变
