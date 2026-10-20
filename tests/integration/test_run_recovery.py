"""A1：事件/终态落库暂时失败后，Run 在数据库恢复时在线进入终态并释放会话，无需重启API。"""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from backend.domain.execution import RunContext, RuntimeOutcome
from backend.persistence import runs
from backend.services.common import ServiceError
from backend.services.runs import MessageInput, RunService
from backend.services.travel import TravelService
from tests.fakes import FakeRuntime
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


async def down(*args: object, **kwargs: object) -> None:
    raise OperationalError("x", {}, Exception("db down"))


@pytest.mark.parametrize("broken", ["append_event", "finish"])
def test_transient_persistence_failure_recovers_online(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    monkeypatch: pytest.MonkeyPatch,
    broken: str,
) -> None:
    runner, travel, context = travel_setup
    runtime = FakeRuntime(RuntimeOutcome(text="done", sdk_session_id="s"), text=("hello",))
    service = RunService(travel.database, runtime_factory=lambda _: runtime)
    monkeypatch.setattr(runs, broken, down)

    async def exercise() -> None:
        first = await service.submit(
            context.user_id, context.session_id, MessageInput(client_message_id=uuid4(), text="q")
        )
        await asyncio.gather(*tuple(service.tasks.values()), return_exceptions=True)
        # 库仍不可用：恢复核对失败，保持 503，不能假报完成。
        monkeypatch.setattr(runs, "recover", down)
        with pytest.raises(ServiceError, match="恢复核对"):
            await service.get(context.user_id, first.run_id)
        monkeypatch.undo()  # 数据库恢复

        recovered = await service.get(context.user_id, first.run_id)
        assert recovered.status == "partial" and recovered.error_code == "unavailable"
        assert not service.persistence_failures
        # 会话已释放，可继续提交；旧模型调用不被重放。
        second = await service.submit(
            context.user_id,
            context.session_id,
            MessageInput(client_message_id=uuid4(), text="again"),
        )
        await asyncio.gather(*tuple(service.tasks.values()))
        assert second.run_id != first.run_id and len(runtime.resumed) == 2
        events = await service.events(context.user_id, first.run_id, 0)
        assert [e["kind"] for e in events].count("partial") == 1
        await service.close()

    runner.run(exercise())


def test_recovery_also_unblocks_submit_and_cancel(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, travel, context = travel_setup
    service = RunService(
        travel.database, runtime_factory=lambda _: FakeRuntime(RuntimeOutcome(text="done"))
    )
    monkeypatch.setattr(runs, "finish", down)

    async def exercise() -> None:
        first = await service.submit(
            context.user_id, context.session_id, MessageInput(client_message_id=uuid4(), text="q")
        )
        await asyncio.gather(*tuple(service.tasks.values()), return_exceptions=True)
        monkeypatch.undo()
        cancelled = await service.cancel(context.user_id, first.run_id)
        assert cancelled.status == "partial"  # 终态后取消是幂等读取
        await service.submit(
            context.user_id, context.session_id, MessageInput(client_message_id=uuid4(), text="x")
        )
        await asyncio.gather(*tuple(service.tasks.values()))
        await service.close()

    runner.run(exercise())
