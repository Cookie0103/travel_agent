"""R01/R03/R12：真实 PG 最终回答持久化、重启、引用时效和失败边界。"""

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from backend.domain.execution import (
    ErrorCode,
    RunContext,
    RuntimeEvent,
    RuntimeOutcome,
    event_metadata,
)
from backend.domain.plans import StageInput
from backend.persistence import runs
from backend.persistence import travel as repository
from backend.services.common import ServiceError, transaction
from backend.services.history import HistoryService
from backend.services.hotels import HotelService
from backend.services.plans import PlanService
from backend.services.runs import MessageInput, RunService
from backend.services.sessions import DemoLogin, SessionService
from backend.services.travel import TravelService
from tests.fakes import FakeRuntime
from tests.integration.test_planning import destinations, proposal
from tests.integration.test_travel import evidence
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


def test_export_uses_original_user_text_instead_of_server_augmented_prompt(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        async with transaction(travel.database) as db:
            row = await runs.create(
                db,
                context.user_id,
                context.session_id,
                uuid4(),
                "用户原话\n服务端内部续接说明",
                "offline",
                user_text="用户原话",
            )
            await runs.finish(
                db,
                RunContext(context.user_id, context.session_id, row.id),
                RuntimeOutcome(text="回答"),
            )
        exported = await HistoryService(travel.database).export(context.user_id, context.session_id)
        assert "服务端内部续接说明" not in json.dumps(exported, ensure_ascii=False)
        assert "用户原话" in json.dumps(exported, ensure_ascii=False)

    runner.run(exercise())


@pytest.mark.parametrize("code", ["timeout", "provider_error"])
def test_failed_live_answer_keeps_fixed_explanation_and_partial_text(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    monkeypatch: pytest.MonkeyPatch,
    code: ErrorCode,
) -> None:
    runner, travel, context = travel_setup
    service, runtime = live_service(
        travel,
        monkeypatch,
        RuntimeOutcome(code=code, reason="run_timeout"),
    )

    async def exercise() -> None:
        await submit(service, context)
        runtime.outcome = replace(runtime.outcome, text="已查到部分真实结果")
        await submit(service, context)
        page = await HistoryService(travel.database).runs(
            context.user_id, context.session_id, 20, None
        )
        assert page.items[0].answer == f"执行未完成：{code}"
        assert page.items[1].answer == f"执行未完成：{code}\n\n已查到部分真实结果"
        await service.close()

    runner.run(exercise())


def test_scrubbed_itinerary_presentation_retains_owned_draft_quote_refs(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        first, _ = await destinations(travel, context)
        draft = await PlanService(travel).stage(
            context,
            StageInput.model_validate(
                {"change": {"kind": "initial", "proposal": proposal(first).model_dump(mode="json")}}
            ),
        )
        async with transaction(travel.database) as db:
            row = await runs.create(
                db, context.user_id, context.session_id, uuid4(), "行程", "deepseek"
            )
            turn = replace(context, run_id=row.id)
            await runs.append_event(
                db,
                event_metadata(
                    RuntimeEvent(
                        turn,
                        "presentation",
                        presentation={
                            "data": {
                                "component": "itinerary",
                                "draft_id": str(draft.draft_id),
                                "cards": [{"name": "不应存入事件的Google名称"}],
                            }
                        },
                    )
                ),
            )
            await runs.finish(db, turn, RuntimeOutcome(text="合成行程回答"))
            refs = (await runs.events(db, turn.run_id, 0))[-1].payload["evidence_ids"]
            assert isinstance(refs, list)
            assert str(first.evidence_id) in refs

    runner.run(exercise())


def live_service(
    travel: TravelService, monkeypatch: pytest.MonkeyPatch, outcome: RuntimeOutcome
) -> tuple[RunService, FakeRuntime]:
    runtime = FakeRuntime(replace(outcome, sdk_session_id="synthetic"), text=("私有流式中间文字",))
    monkeypatch.setattr(RunService, "_runtime", lambda self, mode, executor: runtime)
    return RunService(travel.database, live_enabled=True), runtime


async def submit(service: RunService, context: RunContext) -> object:
    run = await service.submit(
        context.user_id,
        context.session_id,
        MessageInput(client_message_id=uuid4(), text="合成私有问题", mode="deepseek"),
    )
    await asyncio.gather(*tuple(service.tasks.values()))
    return await service.get(context.user_id, run.run_id)


def test_two_live_turns_survive_history_and_restart_without_replay(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, travel, context = travel_setup
    service, runtime = live_service(travel, monkeypatch, RuntimeOutcome(text="第一轮原回答"))

    async def exercise() -> None:
        await submit(service, context)
        runtime.outcome = RuntimeOutcome(text="第二轮原回答", sdk_session_id="synthetic")
        await submit(service, context)
        await service.close()
        restarted = RunService(travel.database)
        await restarted.initialize()
        page = await HistoryService(travel.database).runs(
            context.user_id, context.session_id, 20, None
        )
        assert [item.answer for item in page.items] == ["第一轮原回答", "第二轮原回答"]
        for item in page.items:
            assert (await restarted.get(context.user_id, item.run_id)).answer == item.answer
            events = await restarted.events(context.user_id, item.run_id, 0)
            assert "私有流式中间文字" not in str(events)
            with pytest.raises(ServiceError) as hidden:
                await restarted.get(uuid4(), item.run_id)
            assert hidden.value.status == 404
        assert len(runtime.resumed) == 2
        await restarted.close()

    runner.run(exercise())


def test_export_history_is_owner_scoped_and_read_only(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], tmp_path: Path
) -> None:
    runner, travel, context = travel_setup

    async def seed() -> tuple[str, str]:
        hotels = HotelService(travel)
        quotes = await hotels.search(context, 1, limit=1)
        payload = await hotels.present(context, 1, (quotes[0].evidence_id,))
        cards = payload["cards"]
        assert isinstance(cards, list) and isinstance(cards[0], dict)
        hotel_name = str(cards[0]["hotel_name"])
        identities = SessionService(travel.database.engine.url, demo_enabled=True)
        try:
            other = await identities.create_demo_user(DemoLogin())
            other_session = await identities.new_session(other.user_id)
            async with transaction(travel.database) as db:
                for user, session, prompt in (
                    (context.user_id, context.session_id, "本人合成问题"),
                    (other.user_id, other_session.session_id, "其他用户的合成私有问题"),
                ):
                    row = await runs.create(db, user, session, uuid4(), prompt, "deepseek")
                    if user == context.user_id:
                        await runs.append_event(
                            db,
                            RuntimeEvent(
                                RunContext(user, session, row.id),
                                "presentation",
                                presentation={"data": payload},
                            ),
                        )
                    await runs.finish(
                        db, RunContext(user, session, row.id), RuntimeOutcome(text="合成回答")
                    )
        finally:
            await identities.close()
        return str(quotes[0].evidence_id), hotel_name

    quote_id, hotel_name = runner.run(seed())
    environment = {
        **os.environ,
        "DATABASE_URL": travel.database.engine.url.render_as_string(hide_password=False),
    }
    output = tmp_path / "history.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/export_history.py",
            "--user",
            str(context.user_id),
            "--out",
            str(output),
        ],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    exported = json.loads(output.read_text(encoding="utf-8"))
    assert exported["read_only"] is True
    assert len(exported["sessions"]) == 1
    assert exported["sessions"][0]["session_id"] == str(context.session_id)
    assert exported["sessions"][0]["runs"][0]["prompt"] == "本人合成问题"
    assert exported["sessions"][0]["runs"][0]["answer"] == "合成回答"
    references = exported["sessions"][0]["runs"][0]["presentation_refs"]
    assert references[0]["evidence_ids"] == [quote_id]
    assert hotel_name not in output.read_text(encoding="utf-8")
    assert "其他用户" not in output.read_text(encoding="utf-8")


def test_final_answer_scrubs_ids_and_truncates_utf8_without_losing_finish(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, travel, context = travel_setup
    internal = str(uuid4())
    service, _ = live_service(
        travel, monkeypatch, RuntimeOutcome(text=f"酒店 evidence_id={internal} " + "旅行" * 20000)
    )

    async def exercise() -> None:
        await submit(service, context)
        page = await HistoryService(travel.database).runs(
            context.user_id, context.session_id, 20, None
        )
        result = page.items[0]
        assert result.status == "completed" and result.error_code is None
        assert internal not in result.answer
        assert result.answer.startswith("酒店 旅行")
        assert len(result.answer.encode("utf-8")) <= 32768
        assert getattr(result, "answer_truncated", False)
        await service.close()

    runner.run(exercise())


def test_finish_failure_returns_503_and_restart_marks_partial(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, travel, context = travel_setup
    service, _ = live_service(travel, monkeypatch, RuntimeOutcome(text="不能冒称已保存"))

    async def fail(*args: object) -> None:
        raise OSError("synthetic commit failure")

    async def exercise() -> None:
        with monkeypatch.context() as scoped:
            scoped.setattr(runs, "finish", fail)
            run = await service.submit(
                context.user_id,
                context.session_id,
                MessageInput(client_message_id=uuid4(), text="合成问题", mode="deepseek"),
            )
            await asyncio.gather(*tuple(service.tasks.values()))
            with pytest.raises(ServiceError) as failure:
                await service.get(context.user_id, run.run_id)
            assert failure.value.status == 503
        restarted = RunService(travel.database)
        await restarted.initialize()
        restored = await restarted.get(context.user_id, run.run_id)
        assert restored.status == "partial" and "不能冒称已保存" not in restored.answer
        await restarted.close()
        await service.close()

    runner.run(exercise())


def test_history_counts_stale_owned_quote_references(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        record = evidence(await travel.get_request(context))
        old = record.model_copy(
            update={
                "retrieved_at": datetime.now(UTC) - timedelta(hours=2),
                "valid_until": datetime.now(UTC) - timedelta(hours=1),
            }
        )
        async with transaction(travel.database) as db:
            await repository.add_evidence(db, context, [old])
            row = await runs.create(
                db, context.user_id, context.session_id, uuid4(), "酒店", "deepseek"
            )
            turn = RunContext(context.user_id, context.session_id, row.id)
            await runs.append_event(
                db,
                RuntimeEvent(
                    turn,
                    "presentation",
                    presentation={
                        "data": {
                            "component": "hotel_comparison",
                            "offer_ids": [str(old.evidence_id)],
                        }
                    },
                ),
            )
            await runs.finish(db, turn, RuntimeOutcome(text="当时报价"))
        page = await HistoryService(travel.database).runs(
            context.user_id, context.session_id, 20, None
        )
        assert getattr(page.items[0], "stale_refs", 0) == 1
        restored = await RunService(travel.database).get(context.user_id, turn.run_id)
        assert getattr(restored, "stale_refs", 0) == 1

    runner.run(exercise())
