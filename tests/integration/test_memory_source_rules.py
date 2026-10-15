"""F10：短引用限可信整条输入，跨用户确认卡拒绝且不改变拥有者事实。"""

import asyncio
from uuid import UUID, uuid4

import pytest

from backend.domain.execution import RunContext, RuntimeOutcome
from backend.services.choices import ChoiceService
from backend.services.common import ServiceError
from backend.services.memory import MemoryService
from backend.services.runs import MessageInput, RunService
from backend.services.sessions import DemoLogin, SessionService
from backend.services.travel import TravelService
from tests.fakes import FakeRuntime
from tests.integration.test_memory import click, proposal
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("text", "quote", "key", "value", "accepted"),
    [
        ("特种兵", "特种兵", "pace", "特种兵", True),
        ("吃素", "吃素", "dietary", "吃素", True),
        ("公交", "公交", "transport", "transit", True),
        ("特　种 兵", "特种兵", "pace", "特种兵", True),
        ("ＡＢＣ", "ABC", "interest", "ABC", True),
        ("我喜欢特种兵旅行", "特种兵", "pace", "特种兵", False),
        ("请帮我查京都公交路线", "公交", "transport", "transit", False),
        ("我想住京都酒店", "我", "interest", "京都", False),
        ("请比较京都酒店", "特种兵", "pace", "特种兵", False),
    ],
)
def test_short_quote_requires_entire_current_user_input(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    text: str,
    quote: str,
    key: str,
    value: str,
    accepted: bool,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        operation: list[dict[str, object]] = [
            {"op": "ADD", "key": key, "value": value, "quote": quote}
        ]
        if accepted:
            _, cards = await proposal(travel, context, text, operation)
            assert len(cards) == 1
            facts = await MemoryService(travel.database).facts(context.user_id)
            assert len(facts) == 1 and facts[0].status == "proposed"
        else:
            with pytest.raises(ServiceError) as error:
                await proposal(travel, context, text, operation)
            assert error.value.status == 422
            assert await MemoryService(travel.database).facts(context.user_id) == ()

    runner.run(exercise())


def test_other_user_cannot_confirm_memory_card(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, owner = travel_setup

    async def exercise() -> None:
        _, cards = await proposal(
            travel,
            owner,
            "我喜欢特种兵旅行",
            [{"op": "ADD", "key": "pace", "value": "特种兵", "quote": "我喜欢特种兵旅行"}],
        )
        memory = MemoryService(travel.database)
        before = await memory.facts(owner.user_id)
        identities = SessionService(travel.database.engine.url, demo_enabled=True)
        fake = FakeRuntime(RuntimeOutcome(text="不应运行"))
        service = RunService(travel.database, runtime_factory=lambda _: fake)
        try:
            other = await identities.create_demo_user(DemoLogin(display_name="卡片隔离测试"))
            session = await identities.new_session(other.user_id)
            for session_id in (session.session_id, owner.session_id):
                with pytest.raises(ServiceError) as error:
                    await service.submit(
                        other.user_id,
                        session_id,
                        MessageInput.model_validate(
                            {
                                "client_message_id": uuid4(),
                                "text": "记住",
                                "expected_revision": 0,
                                "selection": {
                                    "choice_id": cards[0]["choice_id"],
                                    "option_id": "remember",
                                },
                            }
                        ),
                    )
                assert error.value.status == 404
            assert await memory.facts(owner.user_id) == before
            card = await ChoiceService(travel).get(
                owner.user_id, owner.session_id, UUID(str(cards[0]["choice_id"]))
            )
            assert card.answered_option_id is None and not fake.resumed
        finally:
            await service.close()
            await identities.close()

    runner.run(exercise())


def test_whole_short_reply_whitespace_cannot_bypass_rejected_quote(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, owner = travel_setup

    async def exercise() -> None:
        context, cards = await proposal(
            travel,
            owner,
            "特 种 兵",
            [{"op": "ADD", "key": "pace", "value": "特种兵", "quote": "特 种 兵"}],
        )
        await click(travel, context, cards[0], "reject")
        _, next_cards = await proposal(
            travel,
            owner,
            "特 种 兵",
            [{"op": "ADD", "key": "interest", "value": "特种兵", "quote": "特种兵"}],
        )
        assert next_cards == []

    runner.run(exercise())
