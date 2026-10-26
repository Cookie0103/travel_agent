"""真实PG异步记忆抽取：run结束后提议、来源核验、卡片追加与失败隔离。"""

import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.domain.execution import RunContext, RuntimeOutcome
from backend.domain.preferences import PreferenceVersion
from backend.limits import ProbeError
from backend.persistence.models import ChoiceCardRow, MemoryFactRow
from backend.services.common import transaction
from backend.services.memory import MemoryService
from backend.services.memory_extractor import MemoryExtractor
from backend.services.preferences import PreferenceService
from backend.services.runs import MessageInput, RunService, RunView
from backend.services.travel import TravelService
from tests.fakes import FakeRuntime
from tests.integration.test_memory import click
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


class ScriptedCall:
    """按顺序返回预设模型输出，并记录收到的输入；不模拟模型质量。"""

    def __init__(self, *outputs: object) -> None:
        self.outputs, self.payloads = list(outputs), list[dict[str, object]]()

    async def __call__(self, payload: dict[str, object]) -> str:
        self.payloads.append(payload)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return json.dumps(output, ensure_ascii=False)


def service_for(
    travel: TravelService, call: ScriptedCall, answer: str = "好的"
) -> tuple[RunService, FakeRuntime]:
    runtime = FakeRuntime(RuntimeOutcome(text=answer, sdk_session_id="synthetic"))
    service = RunService(
        travel.database,
        live_enabled=True,
        runtime_factory=lambda _: runtime,
        memory_extractor=MemoryExtractor(travel.database, call),
    )
    return service, runtime


async def turn(
    service: RunService, context: RunContext, text: str, mode: str = "deepseek"
) -> RunView:
    run = await service.submit(
        context.user_id,
        context.session_id,
        MessageInput.model_validate(
            {"client_message_id": str(uuid4()), "text": text, "mode": mode}
        ),
    )
    await asyncio.gather(*tuple(service.tasks.values()))
    return run


def op(quote: str, value: str = "慢节奏", **extra: object) -> dict[str, object]:
    return {"op": "ADD", "key": "pace", "value": value, "quote": quote, **extra}


def test_extraction_runs_after_completion_and_appends_confirm_card(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    call = ScriptedCall({"ops": [op("以后都按慢节奏来")]})
    service, _ = service_for(travel, call, answer="明白，会请你在卡片里确认")

    async def exercise() -> None:
        try:
            run = await turn(service, context, "我以后都按慢节奏来，请记住")
            pending = await service.get(context.user_id, run.run_id)
            assert pending.status == "completed"  # 终态不等抽取
            result = await service.memory_settled(run.run_id)
            assert result is not None and result.proposed == 1 and len(result.cards) == 1
            # 抽取器只收到用户原话、助手最终文本和已确认事实，没有工具结果。
            assert set(call.payloads[0]) == {"turns", "active_memory"}
            assert call.payloads[0]["turns"] == [
                {"user": "我以后都按慢节奏来，请记住", "assistant": "明白，会请你在卡片里确认"}
            ]
            done = await service.get(context.user_id, run.run_id)
            assert done.memory_pending is None
            cards = [
                p["presentation"]["data"]  # type: ignore[index]
                for p in done.presentations
                if p.get("tool_name") == "memory_extractor"
            ]
            assert [c["kind"] for c in cards] == ["memory_confirm"]
            async with transaction(travel.database) as db:
                card = await db.get(ChoiceCardRow, cards[0]["choice_id"])
                assert card is not None and card.source_run_id == run.run_id
            await click(travel, context, result.cards[0], "remember")
            facts = await MemoryService(travel.database).facts(context.user_id)
            assert [(f.key, f.value, f.status, f.source_run_id) for f in facts] == [
                ("pace", "慢节奏", "active", run.run_id)
            ]
        finally:
            await service.close()

    runner.run(exercise())


def test_quote_sources_are_recent_user_turns_only_and_duplicates_stay_silent(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    call = ScriptedCall(
        {"ops": []},
        {
            "ops": [
                op("平时都喜欢慢节奏"),  # 上一轮原话：在最近几轮内，可作来源
                op("我推荐你慢节奏", key="evening_end", value="21点"),  # 助手文字不是来源
                {"op": "ADD", "key": "pace", "value": "任意节奏", "quote": "按刚才说的"},
            ]
        },
        {"ops": [op("平时都喜欢慢节奏")]},  # 重读同一句：不重复出卡
    )
    service, runtime = service_for(travel, call)

    async def exercise() -> None:
        try:
            await turn(service, context, "我平时都喜欢慢节奏的旅行")
            runtime.outcome = RuntimeOutcome(text="我推荐你慢节奏", sdk_session_id="synthetic")
            second = await turn(service, context, "以后就按刚才说的记下来")
            result = await service.memory_settled(second.run_id)
            assert result is not None and (result.proposed, result.invalid) == (1, 2)
            third = await turn(service, context, "继续")
            again = await service.memory_settled(third.run_id)
            assert again is not None and again.proposed == 1 and again.cards == ()
            async with transaction(travel.database) as db:
                rows = list(
                    await db.scalars(
                        select(MemoryFactRow).where(MemoryFactRow.user_id == context.user_id)
                    )
                )
            assert [(row.key, row.status) for row in rows] == [("pace", "proposed")]
        finally:
            await service.close()

    runner.run(exercise())


def test_failures_offline_mode_and_forgetting_never_touch_run_outcome(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    call = ScriptedCall(ProbeError("unavailable", "模型不可用"), {"ops": [op("以后都慢节奏")]})
    service, _ = service_for(travel, call)

    async def exercise() -> None:
        try:
            failed = await turn(service, context, "以后都慢节奏")
            result = await service.memory_settled(failed.run_id)
            assert result is not None and result.skipped == "model_unavailable"
            assert (await service.get(context.user_id, failed.run_id)).status == "completed"
            offline = await turn(service, context, "以后都慢节奏", mode="offline")
            assert await service.memory_settled(offline.run_id) is None
            assert len(call.payloads) == 1
            # 用户“忘记全部偏好”后，遗忘前完成的轮次不能再被抽取成提议。
            preferences = PreferenceService(travel.database)
            current = await preferences.get(context.user_id)
            await preferences.change(
                context.user_id, PreferenceVersion(expected_revision=current.revision)
            )
            late = await MemoryExtractor(travel.database, call).extract(
                RunContext(context.user_id, context.session_id, failed.run_id)
            )
            assert late.skipped == "no_source" and len(call.payloads) == 1
            async with transaction(travel.database) as db:
                assert not list(
                    await db.scalars(
                        select(MemoryFactRow).where(MemoryFactRow.user_id == context.user_id)
                    )
                )
        finally:
            await service.close()

    runner.run(exercise())


def test_next_live_turn_waits_for_running_extraction_instead_of_hitting_the_live_lock(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    release = asyncio.Event()

    class SlowCall(ScriptedCall):
        async def __call__(self, payload: dict[str, object]) -> str:
            await release.wait()
            return await super().__call__(payload)

    service, runtime = service_for(travel, SlowCall({"ops": []}, {"ops": []}))

    async def exercise() -> None:
        try:
            first = await turn(service, context, "第一轮")
            assert (await service.get(context.user_id, first.run_id)).memory_pending is True
            second = await service.submit(
                context.user_id,
                context.session_id,
                MessageInput.model_validate(
                    {"client_message_id": str(uuid4()), "text": "第二轮", "mode": "deepseek"}
                ),
            )
            await asyncio.sleep(0.2)
            assert len(runtime.resumed) == 1  # 第二轮还在等抽取，没有发起模型调用
            release.set()
            await asyncio.gather(*tuple(service.tasks.values()))
            assert len(runtime.resumed) == 2
            assert (await service.get(context.user_id, second.run_id)).status == "completed"
        finally:
            release.set()
            await service.close()

    runner.run(exercise())
