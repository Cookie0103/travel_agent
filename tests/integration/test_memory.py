"""真实PG记忆：来源、逐条确认、trip隔离、更新历史及遗忘。"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import URL, select

from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeOutcome
from backend.domain.memory import MemoryProposal
from backend.domain.preferences import PreferencePatch, PreferenceVersion
from backend.persistence import runs, sessions
from backend.persistence.models import MemoryFactRow
from backend.services.choices import ChoiceService
from backend.services.common import ServiceError, transaction
from backend.services.history import HistoryService
from backend.services.memory import MemoryService
from backend.services.preferences import PreferenceService
from backend.services.runs import MessageInput, RunService
from backend.services.sessions import DemoLogin, SessionService
from backend.services.travel import TravelService
from tests.fakes import FakeRuntime
from tests.integration.test_sessions import client as client
from tests.integration.test_sessions import login
from tests.integration.test_travel import travel_setup as travel_setup
from tests.runner import selector_runner

pytestmark = pytest.mark.integration


async def click(
    travel: TravelService, context: RunContext, card: dict[str, object], option: str
) -> None:
    service = RunService(travel.database)
    try:
        await service.submit(
            context.user_id,
            context.session_id,
            MessageInput.model_validate(
                {
                    "client_message_id": str(uuid4()),
                    "text": "选择记忆",
                    "expected_revision": (await travel.read_request(context)).revision,
                    "selection": {"choice_id": card["choice_id"], "option_id": option},
                }
            ),
        )
        await asyncio.gather(*tuple(service.tasks.values()))
    finally:
        await service.close()


async def proposal(
    travel: TravelService, original: RunContext, text: str, ops: list[dict[str, object]]
) -> tuple[RunContext, list[dict[str, object]]]:
    async with transaction(travel.database) as db:
        row = await runs.create(db, original.user_id, original.session_id, uuid4(), text, "offline")
        context = RunContext(original.user_id, original.session_id, row.id)
    cards = await MemoryService(travel.database).propose(
        context, MemoryProposal.model_validate({"ops": ops})
    )
    async with transaction(travel.database) as db:
        await runs.finish(db, context, RuntimeOutcome(text="请逐条选择是否记忆"))
    return context, cards


def test_memory_quote_rejects_tool_poison_and_accepts_only_after_structured_click(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, original = travel_setup

    async def exercise() -> None:
        memory = MemoryService(travel.database)
        with pytest.raises(ServiceError) as error:
            await proposal(
                travel,
                original,
                "我想去京都",
                [{"op": "ADD", "key": "pace", "value": "特种兵", "quote": "我喜欢特种兵"}],
            )
        assert error.value.status == 422
        # 前一次失败创建的合成run由测试显式结束，不能当成业务重试。
        async with transaction(travel.database) as db:
            for _row in await db.scalars(
                select(MemoryFactRow).where(MemoryFactRow.user_id == original.user_id)
            ):
                raise AssertionError("非法来源不能写任何事实")
            for row in await runs.interrupted(db):
                if row.user_id == original.user_id:
                    await runs.finish(
                        db,
                        RunContext(row.user_id, row.session_id, row.id),
                        RuntimeOutcome(text="合成失败结束"),
                    )
        _, cards = await proposal(
            travel,
            original,
            "我喜欢特种兵，常用公共交通",
            [
                {"op": "ADD", "key": "pace", "value": "特种兵", "quote": "我喜欢特种兵"},
                {"op": "ADD", "key": "transport", "value": "transit", "quote": "常用公共交通"},
            ],
        )
        assert len(cards) == 2
        assert (await memory.snapshot(original)) == []
        service = RunService(travel.database)
        for card in cards:
            message = MessageInput.model_validate(
                {
                    "client_message_id": str(uuid4()),
                    "text": "记住这条偏好",
                    "expected_revision": 1,
                    "selection": {"choice_id": card["choice_id"], "option_id": "remember"},
                }
            )
            first = await service.submit(original.user_id, original.session_id, message)
            assert (
                await service.submit(original.user_id, original.session_id, message)
            ).run_id == first.run_id
            await asyncio.gather(*tuple(service.tasks.values()))
        assert {fact["key"] for fact in await memory.snapshot(original)} == {"pace", "transport"}
        assert (
            await PreferenceService(travel.database).get(original.user_id)
        ).transport == "transit"
        assert (await PreferenceService(travel.database).get(original.user_id)).revision == 2
        await service.close()

    runner.run(exercise())


def test_all_memory_cards_of_a_round_are_confirmed_in_one_message(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, original = travel_setup

    async def exercise() -> None:
        memory = MemoryService(travel.database)
        _, cards = await proposal(
            travel,
            original,
            "我喜欢特种兵，常用公共交通",
            [
                {"op": "ADD", "key": "pace", "value": "特种兵", "quote": "我喜欢特种兵"},
                {"op": "ADD", "key": "transport", "value": "transit", "quote": "常用公共交通"},
            ],
        )
        first, second = (str(card["choice_id"]) for card in cards)

        def body(also: list[dict[str, str]], mid: UUID) -> MessageInput:
            return MessageInput.model_validate(
                {
                    "client_message_id": str(mid),
                    "text": "统一确认记忆",
                    "expected_revision": 1,
                    "selection": {"choice_id": first, "option_id": "remember", "also": also},
                }
            )

        service = RunService(travel.database)
        bad = [{"choice_id": first, "option_id": "reject"}]  # 重复同一张卡
        with pytest.raises(ServiceError) as error:
            await service.submit(original.user_id, original.session_id, body(bad, uuid4()))
        assert error.value.status == 422 and await memory.snapshot(original) == []
        picks = [{"choice_id": second, "option_id": "reject"}]
        mid = uuid4()
        run = await service.submit(original.user_id, original.session_id, body(picks, mid))
        again = await service.submit(original.user_id, original.session_id, body(picks, mid))
        assert again.run_id == run.run_id  # 同一消息幂等重放
        with pytest.raises(ServiceError) as conflict:  # 同一消息ID换了选择
            await service.submit(
                original.user_id,
                original.session_id,
                body([{"choice_id": second, "option_id": "remember"}], mid),
            )
        assert conflict.value.status == 409
        await asyncio.gather(*tuple(service.tasks.values()))
        assert {fact["key"] for fact in await memory.snapshot(original)} == {"pace"}
        await service.close()

    runner.run(exercise())


def test_memory_api_owner_history_and_delete(client: TestClient, postgres_url: URL) -> None:
    other = login(client)
    assert client.get("/memory").status_code == 401
    with selector_runner() as runner:
        accounts = SessionService(postgres_url, demo_enabled=True)
        identity = runner.run(accounts.create_demo_user(DemoLogin()))
        owner = {"Authorization": "Bearer " + identity.token}
        assert client.get("/memory", headers=owner).json() == []
        # 手动偏好编辑的HTTP入口已移除；用服务层种子等价的manual事实。
        runner.run(
            PreferenceService(accounts.database).change(
                identity.user_id,
                PreferencePatch.model_validate(
                    {
                        "expected_revision": 0,
                        "set": {"interests": ["茶道"], "transport": "transit"},
                    }
                ),
            )
        )
        runner.run(accounts.close())
    facts = client.get("/memory", headers=owner).json()
    assert {f["key"] for f in facts} == {"interest", "transport"}
    assert all(f["source"] == "manual" and f["valid_from"] for f in facts)
    path = "/memory/" + facts[0]["fact_id"]
    assert client.get(path, headers=other).status_code == 404
    assert (
        client.request("DELETE", path, headers=other, json={"expected_revision": 0}).status_code
        == 404
    )
    assert (
        client.request("DELETE", path, headers=owner, json={"expected_revision": 0}).status_code
        == 409
    )
    assert (
        client.request("DELETE", path, headers=owner, json={"expected_revision": 1}).json()[
            "revision"
        ]
        == 2
    )
    deleted = client.get(path, headers=owner).json()
    assert (
        deleted["status"] == "deleted"
        and deleted["value"] is None
        and deleted["evidence_quote"] == ""
    )
    assert len(client.get("/memory?include_history=true", headers=owner).json()) == 2


def test_forget_again_erases_new_pending_after_empty_tombstone(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        prefs = PreferenceService(travel.database)
        await prefs.change(context.user_id, PreferenceVersion(expected_revision=0))
        _, cards = await proposal(
            travel,
            context,
            "我喜欢特种兵",
            [{"op": "ADD", "key": "pace", "value": "特种兵", "quote": "我喜欢特种兵"}],
        )
        deleted = await prefs.change(context.user_id, PreferenceVersion(expected_revision=1))
        assert deleted.revision == 2
        facts = await MemoryService(travel.database).facts(context.user_id, include_history=True)
        assert len(facts) == 1 and facts[0].status == "deleted"
        assert facts[0].value is None and not facts[0].evidence_quote
        with pytest.raises(ServiceError) as error:
            await click(travel, context, cards[0], "remember")
        assert error.value.status == 409
        assert (
            await prefs.change(context.user_id, PreferenceVersion(expected_revision=2))
        ).revision == 2

    runner.run(exercise())


def test_changed_operation_cannot_reuse_same_quote_card(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await proposal(
            travel,
            context,
            "我想改成慢节奏，不再特种兵",
            [
                {
                    "op": "ADD",
                    "key": "pace",
                    "value": "特种兵",
                    "quote": "我想改成慢节奏，不再特种兵",
                }
            ],
        )
        with pytest.raises(ServiceError) as error:
            await proposal(
                travel,
                context,
                "我想改成慢节奏，不再特种兵",
                [
                    {
                        "op": "ADD",
                        "key": "pace",
                        "value": "慢节奏",
                        "quote": "我想改成慢节奏，不再特种兵",
                    }
                ],
            )
        assert error.value.status == 409
        facts = await MemoryService(travel.database).facts(context.user_id)
        assert len(facts) == 1 and facts[0].value == "特种兵"

    runner.run(exercise())


def test_trip_override_update_history_rejection_and_selective_forget(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        memory = MemoryService(travel.database)
        _, cards = await proposal(
            travel,
            context,
            "我喜欢特种兵",
            [{"op": "ADD", "key": "pace", "value": "特种兵", "quote": "我喜欢特种兵"}],
        )
        await click(travel, context, cards[0], "remember")
        old = next(f for f in await memory.facts(context.user_id) if f.status == "active")
        _, cards = await proposal(
            travel,
            context,
            "这次我想慢节奏",
            [
                {
                    "op": "UPDATE",
                    "key": "pace",
                    "value": "慢节奏",
                    "quote": "这次我想慢节奏",
                    "target_fact_id": str(old.fact_id),
                    "scope": "trip",
                }
            ],
        )
        await click(travel, context, cards[0], "trip")
        assert [f["value"] for f in await memory.snapshot(context)] == ["慢节奏"]
        async with transaction(travel.database) as db:
            other_session = await sessions.create_session(db, context.user_id)
            other = RunContext(context.user_id, other_session.id, uuid4())
        assert [f["value"] for f in await memory.snapshot(other)] == ["特种兵"]
        _, cards = await proposal(
            travel,
            context,
            "以后我喜欢标准",
            [
                {
                    "op": "UPDATE",
                    "key": "pace",
                    "value": "标准",
                    "quote": "以后我喜欢标准",
                    "target_fact_id": str(old.fact_id),
                }
            ],
        )
        await click(travel, context, cards[0], "remember")
        historic = await memory.get(context.user_id, old.fact_id)
        assert historic.status == "superseded" and historic.invalidated_at is not None
        assert historic.superseded_by is not None
        assert (await memory.get(context.user_id, historic.superseded_by)).value == "标准"
        _, cards = await proposal(
            travel,
            context,
            "我喜欢茶道",
            [{"op": "ADD", "key": "interest", "value": "茶道", "quote": "我喜欢茶道"}],
        )
        await click(travel, context, cards[0], "reject")
        _, again = await proposal(
            travel,
            context,
            "我喜欢茶道",
            [{"op": "ADD", "key": "interest", "value": "茶道", "quote": "我喜欢茶道"}],
        )
        assert again == []
        current = await PreferenceService(travel.database).get(context.user_id)
        await memory.delete(
            context.user_id,
            historic.superseded_by,
            PreferenceVersion(expected_revision=current.revision),
        )
        forgotten = await memory.get(context.user_id, historic.superseded_by)
        assert (
            forgotten.status == "deleted"
            and forgotten.value is None
            and not forgotten.evidence_quote
        )
        assert await memory.snapshot(other) == []
        assert [f["value"] for f in await memory.snapshot(context)] == ["慢节奏"]

    runner.run(exercise())


def test_selective_forget_invalidates_dependent_proposal_and_cross_user_update_is_404(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        prefs = PreferenceService(travel.database)
        await prefs.change(
            context.user_id,
            PreferencePatch.model_validate(
                {"expected_revision": 0, "set": {"transport": "transit"}}
            ),
        )
        memory = MemoryService(travel.database)
        fact = (await memory.facts(context.user_id))[0]
        _, cards = await proposal(
            travel,
            context,
            "我改成出租车",
            [
                {
                    "op": "UPDATE",
                    "key": "transport",
                    "value": "taxi",
                    "quote": "我改成出租车",
                    "target_fact_id": str(fact.fact_id),
                }
            ],
        )
        other_id = uuid4()
        with pytest.raises(ServiceError) as error:
            await memory.get(other_id, fact.fact_id)
        assert error.value.status == 404
        # target从另一个真实用户获得，当前用户提交其ID不能泄露任何状态。
        async with transaction(travel.database) as db:
            foreign_user = await sessions.create_user(
                db, "隔离合成", uuid4().hex, datetime.now(UTC) + timedelta(days=1)
            )
            foreign = MemoryFactRow(
                user_id=foreign_user.id,
                key="transport",
                value="transit",
                scope="long_term",
                status="active",
                source="manual",
            )
            db.add(foreign)
            await db.flush()
            foreign_id = foreign.id
        with pytest.raises(ServiceError) as error:
            await proposal(
                travel,
                context,
                "我改成出租车",
                [
                    {
                        "op": "UPDATE",
                        "key": "transport",
                        "value": "taxi",
                        "quote": "我改成出租车",
                        "target_fact_id": str(foreign_id),
                    }
                ],
            )
        assert error.value.status == 404
        await memory.delete(context.user_id, fact.fact_id, PreferenceVersion(expected_revision=1))
        facts = await memory.facts(context.user_id, include_history=True)
        assert all(
            f.status == "deleted" and f.value is None and not f.evidence_quote for f in facts
        )
        card = await ChoiceService(travel).get(
            context.user_id, context.session_id, UUID(str(cards[0]["choice_id"]))
        )
        assert card.stale and "出租车" not in card.question
        assert await memory.snapshot(context) == []

    runner.run(exercise())


def test_trip_update_of_interest_shadows_only_target_in_current_session(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await PreferenceService(travel.database).change(
            context.user_id,
            PreferencePatch.model_validate(
                {"expected_revision": 0, "set": {"interests": ["茶道", "庭园"]}}
            ),
        )
        memory = MemoryService(travel.database)
        fact = next(f for f in await memory.facts(context.user_id) if f.value == "茶道")
        _, cards = await proposal(
            travel,
            context,
            "这次换成美术",
            [
                {
                    "op": "UPDATE",
                    "key": "interest",
                    "value": "美术",
                    "scope": "trip",
                    "quote": "这次换成美术",
                    "target_fact_id": str(fact.fact_id),
                }
            ],
        )
        await click(travel, context, cards[0], "trip")
        assert {f["value"] for f in await memory.snapshot(context)} == {"美术", "庭园"}
        assert (await PreferenceService(travel.database).get(context.user_id)).interests == (
            "茶道",
            "庭园",
        )

    runner.run(exercise())


def test_rejected_quote_cannot_be_reoffered_with_another_key(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        _, cards = await proposal(
            travel,
            context,
            "我喜欢安静散步",
            [{"op": "ADD", "key": "interest", "value": "散步", "quote": "我喜欢安静散步"}],
        )
        await click(travel, context, cards[0], "reject")
        _, again = await proposal(
            travel,
            context,
            "我喜欢安静散步",
            [{"op": "ADD", "key": "avoid", "value": "喧闹", "quote": "我喜欢安静散步"}],
        )
        assert again == []

    runner.run(exercise())


def test_snapshot_is_bounded_and_capacity_failure_rolls_back_click(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        interests = [f"兴趣{index}" + "长" * 60 for index in range(20)]
        avoid = [f"避开{index}" + "长" * 60 for index in range(20)]
        await PreferenceService(travel.database).change(
            context.user_id,
            PreferencePatch.model_validate(
                {"expected_revision": 0, "set": {"interests": interests, "soft_constraints": avoid}}
            ),
        )
        memory = MemoryService(travel.database)
        snapshot = await memory.snapshot(context)
        assert 0 < len(snapshot) <= 30 and len(json.dumps(snapshot, ensure_ascii=False)) <= 2000
        _, cards = await proposal(
            travel,
            context,
            "我还喜欢花道",
            [{"op": "ADD", "key": "interest", "value": "花道", "quote": "我还喜欢花道"}],
        )
        with pytest.raises(ServiceError) as error:
            await click(travel, context, cards[0], "remember")
        assert error.value.status == 422
        assert (await PreferenceService(travel.database).get(context.user_id)).revision == 1
        assert sum(f.status == "proposed" for f in await memory.facts(context.user_id)) == 1

    runner.run(exercise())


def test_update_trip_to_long_term_cannot_leave_duplicate_scalar(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await PreferenceService(travel.database).change(
            context.user_id,
            PreferencePatch.model_validate(
                {"expected_revision": 0, "set": {"transport": "transit"}}
            ),
        )
        _, cards = await proposal(
            travel,
            context,
            "这次想用出租车",
            [
                {
                    "op": "ADD",
                    "key": "transport",
                    "value": "taxi",
                    "scope": "trip",
                    "quote": "这次想用出租车",
                }
            ],
        )
        await click(travel, context, cards[0], "trip")
        memory = MemoryService(travel.database)
        target = next(f for f in await memory.facts(context.user_id) if f.scope == "trip")
        _, cards = await proposal(
            travel,
            context,
            "以后常用步行",
            [
                {
                    "op": "UPDATE",
                    "key": "transport",
                    "value": "walk",
                    "quote": "以后常用步行",
                    "target_fact_id": str(target.fact_id),
                }
            ],
        )
        with pytest.raises(ServiceError) as error:
            await click(travel, context, cards[0], "remember")
        assert error.value.status == 409
        assert (
            await PreferenceService(travel.database).get(context.user_id)
        ).transport == "transit"
        assert (await memory.get(context.user_id, target.fact_id)).status == "active"

    runner.run(exercise())


def test_pending_update_card_becomes_stale_when_target_was_replaced(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await PreferenceService(travel.database).change(
            context.user_id,
            PreferencePatch.model_validate(
                {"expected_revision": 0, "set": {"transport": "transit"}}
            ),
        )
        memory = MemoryService(travel.database)
        target = (await memory.facts(context.user_id))[0]
        _, cards = await proposal(
            travel,
            context,
            "以后用出租车，也想改成步行",
            [
                {
                    "op": "UPDATE",
                    "key": "transport",
                    "value": "taxi",
                    "quote": "以后用出租车",
                    "target_fact_id": str(target.fact_id),
                },
                {
                    "op": "UPDATE",
                    "key": "transport",
                    "value": "walk",
                    "quote": "想改成步行",
                    "target_fact_id": str(target.fact_id),
                },
            ],
        )
        await click(travel, context, cards[0], "remember")
        card = await ChoiceService(travel).get(
            context.user_id, context.session_id, UUID(str(cards[1]["choice_id"]))
        )
        assert card.stale

    runner.run(exercise())


def test_unchanged_preference_fields_keep_fact_identity_and_source(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        _, cards = await proposal(
            travel,
            context,
            "我喜欢茶道",
            [{"op": "ADD", "key": "interest", "value": "茶道", "quote": "我喜欢茶道"}],
        )
        await click(travel, context, cards[0], "remember")
        memory = MemoryService(travel.database)
        before = (await memory.facts(context.user_id))[0]
        await PreferenceService(travel.database).change(
            context.user_id,
            PreferencePatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {"interests": ["茶道"], "soft_constraints": [], "transport": "transit"},
                }
            ),
        )
        fact = await memory.get(context.user_id, before.fact_id)
        assert (
            fact.status == "active"
            and fact.source == "user_utterance"
            and fact.evidence_quote == "我喜欢茶道"
        )

    runner.run(exercise())


def test_confirm_generated_instructions_are_not_user_quotes(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        _, cards = await proposal(
            travel,
            context,
            "我喜欢茶道",
            [{"op": "ADD", "key": "interest", "value": "茶道", "quote": "我喜欢茶道"}],
        )
        checked: list[int] = []

        class Runtime(FakeRuntime):
            async def execute(
                self,
                current: RunContext,
                prompt: str,
                sdk_session_id: str | None,
                emit: EventSink,
                cancelled: asyncio.Event,
            ) -> RuntimeOutcome:
                memory = MemoryService(travel.database)
                try:
                    await memory.propose(
                        current,
                        MemoryProposal.model_validate(
                            {
                                "ops": [
                                    {
                                        "op": "ADD",
                                        "key": "interest",
                                        "value": "伪原话",
                                        "quote": "以服务端memory事实为准",
                                    }
                                ]
                            }
                        ),
                    )
                except ServiceError as error:
                    checked.append(error.status)
                await memory.propose(
                    current,
                    MemoryProposal.model_validate(
                        {
                            "ops": [
                                {
                                    "op": "ADD",
                                    "key": "avoid",
                                    "value": "早起",
                                    "quote": "我不喜欢早起",
                                }
                            ]
                        }
                    ),
                )
                return RuntimeOutcome(text="继续逐条确认")

        service = RunService(
            travel.database, runtime_factory=lambda executor: Runtime(RuntimeOutcome(text="合成"))
        )
        try:
            await service.submit(
                context.user_id,
                context.session_id,
                MessageInput.model_validate(
                    {
                        "client_message_id": str(uuid4()),
                        "text": "我不喜欢早起",
                        "expected_revision": 1,
                        "selection": {"choice_id": cards[0]["choice_id"], "option_id": "remember"},
                    }
                ),
            )
            await asyncio.gather(*tuple(service.tasks.values()))
            assert checked == [422]
            facts = await MemoryService(travel.database).facts(context.user_id)
            assert {f.value for f in facts} == {"茶道", "早起"}
        finally:
            await service.close()

    runner.run(exercise())


def test_history_limit_cannot_hide_current_facts(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await PreferenceService(travel.database).change(
            context.user_id,
            PreferencePatch.model_validate(
                {"expected_revision": 0, "set": {"transport": "transit"}}
            ),
        )
        async with transaction(travel.database) as db:
            for index in range(105):
                db.add(
                    MemoryFactRow(
                        user_id=context.user_id,
                        key="interest",
                        value=str(index),
                        scope="long_term",
                        status="rejected",
                        source="user_utterance",
                    )
                )
        facts = await MemoryService(travel.database).facts(context.user_id, include_history=True)
        assert any(f.status == "active" and f.value == "transit" for f in facts)
        assert len(facts) == 101

    runner.run(exercise())


def test_second_pending_same_interest_cannot_duplicate_active_value(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        _, cards = await proposal(
            travel,
            context,
            "我喜欢茶道，也常去喝茶",
            [
                {"op": "ADD", "key": "interest", "value": "茶道", "quote": "我喜欢茶道"},
                {"op": "ADD", "key": "interest", "value": "茶道", "quote": "也常去喝茶"},
            ],
        )
        await click(travel, context, cards[0], "remember")
        with pytest.raises(ServiceError) as error:
            await click(travel, context, cards[1], "remember")
        assert error.value.status == 409
        assert (await PreferenceService(travel.database).get(context.user_id)).interests == (
            "茶道",
        )

    runner.run(exercise())


def test_choice_history_shows_raw_user_message_not_generated_instructions(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        _, cards = await proposal(
            travel,
            context,
            "我喜欢茶道",
            [{"op": "ADD", "key": "interest", "value": "茶道", "quote": "我喜欢茶道"}],
        )
        await click(travel, context, cards[0], "remember")
        page = await HistoryService(travel.database).runs(
            context.user_id, context.session_id, 20, None
        )
        assert page.items[-1].prompt == "选择记忆"

    runner.run(exercise())
