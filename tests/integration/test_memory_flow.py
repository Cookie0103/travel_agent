"""真实PG：长期偏好跨会话进入模型上下文、合并记忆确认卡（草稿之后一组、默认记住、一次确认）。离线，无付费调用。"""

import asyncio
import json
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from backend.domain.choices import ChoiceCard
from backend.domain.execution import RunContext, RuntimeOutcome
from backend.domain.memory import MemoryProposal
from backend.domain.preferences import PreferenceVersion
from backend.domain.travel_request import RequestPatch
from backend.persistence.models import ChoiceCardRow, MemoryFactRow
from backend.providers.claude_agent.database_tools import DatabaseTools
from backend.services.choices import ChoiceService
from backend.services.common import transaction
from backend.services.memory import MemoryService
from backend.services.preferences import PreferenceService
from backend.services.runs import MessageInput, RunService
from backend.services.sessions import SessionService
from backend.services.travel import TravelService
from backend.tools.travel import TravelToolExecutor
from tests.integration.test_ask_and_select import choice_card, finish, goals, run_of, submit_message
from tests.integration.test_memory import click, proposal
from tests.integration.test_planning import destinations
from tests.integration.test_planning import proposal as stage_proposal
from tests.integration.test_runs import WaitingRuntime
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("fixed_today")]

Setup = tuple[asyncio.Runner, TravelService, RunContext]
PREFS = "我平时喜欢特种兵节奏，常用公共交通，七点半起床，晚上十点结束"
OPS: list[dict[str, object]] = [
    {"op": "ADD", "key": "pace", "value": "特种兵", "quote": "我平时喜欢特种兵节奏"},
    {"op": "ADD", "key": "transport", "value": "transit", "quote": "常用公共交通"},
    {"op": "ADD", "key": "wake_time", "value": "7:30 左右", "quote": "七点半起床"},
    {"op": "ADD", "key": "evening_end", "value": "22:00 左右", "quote": "晚上十点结束"},
]


async def remember_all(travel: TravelService, context: RunContext) -> None:
    """四项长期偏好：逐条提议，再用同一次结构化点击(also)全部“记住”。"""
    _, cards = await proposal(travel, context, PREFS, OPS)
    first, *rest = cards
    service = RunService(travel.database)
    try:
        await service.submit(
            context.user_id,
            context.session_id,
            MessageInput.model_validate(
                {
                    "client_message_id": str(uuid4()),
                    "text": "统一确认记忆",
                    "expected_revision": (await travel.read_request(context)).revision,
                    "selection": {
                        "choice_id": first["choice_id"],
                        "option_id": "remember",
                        "also": [
                            {"choice_id": c["choice_id"], "option_id": "remember"} for c in rest
                        ],
                    },
                }
            ),
        )
        await asyncio.gather(*tuple(service.tasks.values()))
    finally:
        await service.close()


async def other_session(travel: TravelService, context: RunContext) -> RunContext:
    created = await SessionService(travel.database.engine.url).new_session(context.user_id)
    return await run_of(travel, RunContext(context.user_id, created.session_id))


async def model_context(travel: TravelService, context: RunContext) -> str:
    """worker 拼在本轮用户消息前的就是 DatabaseTools.context_snapshot 的这段前置块。"""
    tools = DatabaseTools(asyncio.get_running_loop(), travel.database)
    return (await tools.context_snapshot(context))[0]


def state_of(text: str) -> dict[str, object]:
    """前置块里状态是单独一行JSON，位于标题行与</server_state>之间。"""
    state = json.loads(next(line for line in text.splitlines() if line.startswith("{")))
    assert isinstance(state, dict)
    return state


def memory_of(text: str) -> list[dict[str, object]]:
    memory = state_of(text)["memory"]
    assert isinstance(memory, list)
    return memory


# ---------------- 决定1：长期偏好每次都进模型上下文，trip不外泄 ----------------


def test_new_session_context_has_confirmed_long_term_prefs_and_trip_fact_does_not_leak(
    travel_setup: Setup,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await remember_all(travel, context)
        _, trip = await proposal(
            travel,
            context,
            "这次想只吃素食，不要荤",
            [
                {
                    "op": "ADD",
                    "key": "dietary",
                    "value": "这次只吃素",
                    "scope": "trip",
                    "quote": "这次想只吃素食",
                }
            ],
        )
        await click(travel, context, trip[0], "trip")
        fresh = await other_session(travel, context)
        seen = memory_of(await model_context(travel, fresh))
        assert {(f["key"], f["value"], f["scope"]) for f in seen} == {
            ("pace", "特种兵", "long_term"),
            ("transport", "transit", "long_term"),
            ("wake_time", "7:30 左右", "long_term"),
            ("evening_end", "22:00 左右", "long_term"),
        }  # 新会话：四项都在，另一会话的trip事实不在
        origin = memory_of(await model_context(travel, await run_of(travel, context)))
        assert ("dietary", "这次只吃素", "trip") in {
            (f["key"], f["value"], f["scope"]) for f in origin
        }  # 原会话仍能看到自己的trip事实
        # 之后每个用户轮次都重新注入(不依赖会话内是否提过)
        again = memory_of(await model_context(travel, await run_of(travel, fresh)))
        assert {f["key"] for f in again} == {"pace", "transport", "wake_time", "evening_end"}

    runner.run(exercise())


def test_snapshot_puts_single_value_prefs_before_many_interests(travel_setup: Setup) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        async with transaction(travel.database) as db:
            for index in range(25):  # 先写大量长兴趣：它们占满30条/2000字上限
                db.add(
                    MemoryFactRow(
                        user_id=context.user_id,
                        key="interest",
                        value=f"兴趣{index}" + "长" * 60,
                        scope="long_term",
                        status="active",
                        source="manual",
                        ordinal=index,
                    )
                )
            for ordinal, (key, value) in enumerate(
                (("pace", "慢节奏"), ("transport", "walk"), ("wake_time", "8:30 左右"))
            ):
                db.add(
                    MemoryFactRow(
                        user_id=context.user_id,
                        key=key,
                        value=value,
                        scope="long_term",
                        status="active",
                        source="manual",
                        ordinal=20 + ordinal,  # 多次更新后序号靠后
                    )
                )
        snapshot = await MemoryService(travel.database).snapshot(context)
        assert {"pace", "transport", "wake_time"} <= {f["key"] for f in snapshot}
        assert len(json.dumps(snapshot, ensure_ascii=False)) <= 2000

    runner.run(exercise())


def test_forgetting_one_fact_moves_the_boundary_but_keeps_other_facts_in_context(
    travel_setup: Setup,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await remember_all(travel, context)
        fresh = await other_session(travel, context)
        await finish(travel, fresh)  # 删除前的一轮已完成对话
        facts = {f.key: f for f in await MemoryService(travel.database).facts(context.user_id)}
        version = PreferenceVersion(
            expected_revision=(
                await PreferenceService(travel.database).get(context.user_id)
            ).revision
        )
        await MemoryService(travel.database).delete(context.user_id, facts["pace"].fact_id, version)
        later = await run_of(travel, replace(fresh, run_id=None))  # type: ignore[arg-type]
        text = await model_context(travel, later)
        state = state_of(text)
        # 边界只截断删除前的对话回顾，不隐藏其余仍有效的事实
        assert {f["key"] for f in memory_of(text)} == {"transport", "wake_time", "evening_end"}
        assert state["recent_dialogue"] == []

    runner.run(exercise())


# ---------------- 决定3：草稿之后一组合并确认卡 ----------------


ANSWERS = {
    "pace": ["intensive"],
    "wake_text": ["7:30"],
    "evening": ["e2200"],
    "arrival": ["a1500"],
    "departure": ["d1200"],
    "companion": ["couple"],
    "transport": ["walk"],
}


async def answered_trip(
    travel: TravelService, context: RunContext, **answers: list[str]
) -> tuple[RunService, RunContext]:
    """合并选择卡答完：返回仍在运行的当前执行(用于暂存草稿)。"""
    service = RunService(
        travel.database, runtime_factory=lambda _: WaitingRuntime(RuntimeOutcome(text="x"))
    )
    first = await run_of(travel, context)
    card = choice_card(await goals(travel, first, "itinerary"))
    await finish(travel, first)
    request = await travel.read_request(context)
    submitted = await service.submit(
        context.user_id, context.session_id, submit_message(request, card, "confirm", **answers)
    )
    return service, RunContext(context.user_id, context.session_id, submitted.run_id)


async def stage(travel: TravelService, run: RunContext):  # type: ignore[no-untyped-def]
    first, _ = await destinations(travel, run)
    return await TravelToolExecutor(travel).execute(
        run,
        "stage_plan_change",
        {"change": {"kind": "initial", "proposal": stage_proposal(first).model_dump(mode="json")}},
    )


async def memory_cards(travel: TravelService, run: RunContext) -> list[ChoiceCardRow]:
    async with transaction(travel.database) as db:
        return list(
            await db.scalars(
                select(ChoiceCardRow).where(
                    ChoiceCardRow.session_id == run.session_id,
                    ChoiceCardRow.kind == "memory_confirm",
                )
            )
        )


async def facts_by_key(travel: TravelService, user_id: UUID) -> dict[str, list[tuple[str, str]]]:
    result: dict[str, list[tuple[str, str]]] = {}
    for fact in await MemoryService(travel.database).facts(user_id, include_history=True):
        result.setdefault(fact.key, []).append((fact.status, fact.scope))
    return result


def test_merged_group_is_issued_once_after_the_draft_with_defaults_and_one_confirm(
    travel_setup: Setup,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        service, active = await answered_trip(travel, context, **ANSWERS)
        # 没有草稿：不发，也不建事实
        assert await ChoiceService(travel).merge_memory_cards(active) == []
        assert await memory_cards(travel, active) == []
        staged = await stage(travel, active)
        assert staged.code is None, staged
        cards = staged.data["memory_choices"]
        assert isinstance(cards, list)
        views = [ChoiceCard.model_validate(c) for c in cards]
        assert [v.question for v in views] == [
            "旅行节奏：特种兵。是否保存？",
            "平时起床：7:30。是否保存？",
            "晚上结束：22:00 左右。是否保存？",
            "交通偏好：步行。是否保存？",
        ]  # 只含四项可长期偏好；到达/离开/同行等行程专属项不在
        assert all(v.default_option_id == "remember" for v in views)
        assert all(
            [o.option_id for o in v.options] == ["remember", "trip", "reject"] for v in views
        )
        # 同一轮再暂存：不再发第二组、不重复建事实
        again = await stage(travel, active)
        assert again.code is None
        assert {c["choice_id"] for c in again.data.get("memory_choices", [])} == {
            c["choice_id"] for c in cards
        }
        assert len(await memory_cards(travel, active)) == 4
        # 草稿没确认前，模型快照里还没有这些偏好(proposed不生效)
        assert await MemoryService(travel.database).snapshot(active) == []
        # 一次提交：记住/这次而已/不要记混选
        request = await travel.read_request(active)
        picks = [
            (views[0], "remember"),
            (views[1], "remember"),
            (views[2], "trip"),
            (views[3], "reject"),
        ]
        (first, first_option), *rest = picks
        await service.cancel(context.user_id, active.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        confirm = await service.submit(
            context.user_id,
            context.session_id,
            MessageInput.model_validate(
                {
                    "client_message_id": str(uuid4()),
                    "text": "统一确认记忆",
                    "expected_revision": request.revision,
                    "selection": {
                        "choice_id": str(first.choice_id),
                        "option_id": first_option,
                        "also": [{"choice_id": str(v.choice_id), "option_id": o} for v, o in rest],
                    },
                }
            ),
        )
        await service.cancel(context.user_id, confirm.run_id)  # 等待型运行时需要显式结束
        await asyncio.gather(*tuple(service.tasks.values()))
        facts = await facts_by_key(travel, context.user_id)
        assert facts["pace"] == [("active", "long_term")]
        assert facts["wake_time"] == [("active", "long_term")]
        assert facts["evening_end"] == [("active", "trip")]
        assert [status for status, _ in facts["transport"]] == ["rejected"]
        assert set(facts) == {"pace", "wake_time", "evening_end", "transport"}
        await service.close()
        # 新会话：模型上下文有节奏+起床，没有这次而已的晚上结束，也没有被拒的交通
        fresh = await other_session(travel, context)
        assert {f["key"] for f in memory_of(await model_context(travel, fresh))} == {
            "pace",
            "wake_time",
        }

    runner.run(exercise())


def test_known_long_term_prefs_are_not_asked_again_and_rejected_or_unchanged_not_reproposed(
    travel_setup: Setup,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        service, active = await answered_trip(travel, context, **ANSWERS)
        staged = await stage(travel, active)
        cards = [ChoiceCard.model_validate(c) for c in staged.data["memory_choices"]]
        by_question = {c.question.split("：")[0]: c for c in cards}
        await service.cancel(context.user_id, active.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        request = await travel.read_request(context)
        confirm = await service.submit(
            context.user_id,
            context.session_id,
            MessageInput.model_validate(
                {
                    "client_message_id": str(uuid4()),
                    "text": "统一确认记忆",
                    "expected_revision": request.revision,
                    "selection": {
                        "choice_id": str(by_question["旅行节奏"].choice_id),
                        "option_id": "remember",
                        "also": [
                            {
                                "choice_id": str(by_question["交通偏好"].choice_id),
                                "option_id": "reject",
                            },
                            {
                                "choice_id": str(by_question["平时起床"].choice_id),
                                "option_id": "remember",
                            },
                            {
                                "choice_id": str(by_question["晚上结束"].choice_id),
                                "option_id": "remember",
                            },
                        ],
                    },
                }
            ),
        )
        await service.cancel(context.user_id, confirm.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        await service.close()
        # 新会话：节奏/起床/晚上结束已确认，不再出现在合并卡；交通被拒绝所以仍会问
        fresh = await other_session(travel, context)
        await travel.patch_request(
            fresh,
            RequestPatch.model_validate(
                {
                    "expected_revision": (await travel.read_request(fresh)).revision,
                    "set": {
                        "city": "京都",
                        "adults": 2,
                        "child_ages": [],
                        "rooms": 1,
                        "start_date": "2026-11-03",
                        "end_date": "2026-11-05",
                        "hard_constraints": ["住宿：无要求", "房型：无要求", "床型：无要求"],
                    },
                }
            ),
        )
        card = choice_card(await goals(travel, fresh, "itinerary"))
        assert card.form and [g.key for g in card.form.groups] == [
            "arrival", "departure", "companion", "transport",
        ]  # fmt: skip
        # 这次又选步行(曾被拒绝)：草稿之后不再提议；到达/离开/同行从不提议
        await finish(travel, fresh)
        service = RunService(
            travel.database, runtime_factory=lambda _: WaitingRuntime(RuntimeOutcome(text="x"))
        )
        request = await travel.read_request(fresh)
        submitted = await service.submit(
            context.user_id,
            fresh.session_id,
            submit_message(request, card, "confirm", transport=["walk"], arrival=["a1500"]),
        )
        run = RunContext(context.user_id, fresh.session_id, submitted.run_id)
        staged = await stage(travel, run)
        assert staged.code is None and "memory_choices" not in staged.data
        assert await memory_cards(travel, run) == []
        await service.cancel(context.user_id, submitted.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        await service.close()

    runner.run(exercise())


# ---------------- 对话里明说的偏好、以及“这次想轻松” ----------------


def test_chat_stated_change_is_deferred_until_the_draft_then_merged_as_an_update(
    travel_setup: Setup,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await remember_all(travel, context)
        fresh = await other_session(travel, context)
        await travel.patch_request(
            fresh,
            RequestPatch.model_validate(
                {
                    "expected_revision": (await travel.read_request(fresh)).revision,
                    "set": {
                        "city": "京都",
                        "adults": 2,
                        "child_ages": [],
                        "rooms": 1,
                        "start_date": "2026-11-03",
                        "end_date": "2026-11-05",
                        "hard_constraints": ["住宿：无要求", "房型：无要求", "床型：无要求"],
                        "transport": "transit",
                    },
                }
            ),
        )
        await goals(travel, fresh, "itinerary")
        await finish(travel, fresh)
        # 长期偏好都已确认：合并选择卡只问行程专属项
        pace_fact = next(
            f
            for f in await MemoryService(travel.database).facts(context.user_id)
            if f.key == "pace"
        )
        text = "以后我都想要慢节奏，不想赶了"
        memory_service = MemoryService(travel.database)
        ops = MemoryProposal.model_validate(
            {
                "ops": [
                    {
                        "op": "UPDATE",
                        "key": "pace",
                        "value": "慢节奏",
                        "quote": "以后我都想要慢节奏",
                        "target_fact_id": str(pace_fact.fact_id),
                    }
                ]
            }
        )
        async with transaction(travel.database) as db:
            from backend.persistence import runs

            row = await runs.create(
                db, fresh.user_id, fresh.session_id, uuid4(), text, "offline", user_text=text
            )
        run = RunContext(fresh.user_id, fresh.session_id, row.id)
        cards, deferred = await memory_service.propose_with_deferred(run, ops)
        assert cards == [] and deferred == 1  # 规划进行中、草稿之前：不发卡
        assert await ChoiceService(travel).merge_memory_cards(run) == []  # 没有草稿仍不发
        await travel.patch_request(
            run,
            RequestPatch.model_validate(
                {
                    "expected_revision": (await travel.read_request(run)).revision,
                    "set": {
                        "hard_constraints": [
                            "住宿：无要求",
                            "房型：无要求",
                            "床型：无要求",
                            "节奏：慢节奏",
                        ]
                    },
                }
            ),
        )
        staged = await stage(travel, run)
        assert staged.code is None
        merged = [ChoiceCard.model_validate(c) for c in staged.data["memory_choices"]]
        assert [m.question for m in merged] == ["旅行节奏：比较轻松。是否保存？"]
        assert merged[0].default_option_id == "remember"
        await finish(travel, run)
        # 点击记住：旧值被取代，新值成为长期偏好；其余三项不变
        await click(travel, run, merged[0].model_dump(mode="json"), "remember")
        later = memory_of(await model_context(travel, await other_session(travel, context)))
        assert {(f["key"], f["value"]) for f in later} == {
            ("pace", "慢节奏"),
            ("transport", "transit"),
            ("wake_time", "7:30 左右"),
            ("evening_end", "22:00 左右"),
        }

    runner.run(exercise())


def test_this_time_relaxed_with_a_long_term_pace_changes_no_memory_and_issues_no_card(
    travel_setup: Setup,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await remember_all(travel, context)
        before = await facts_by_key(travel, context.user_id)
        fresh = await other_session(travel, context)
        await travel.patch_request(
            fresh,
            RequestPatch.model_validate(
                {
                    "expected_revision": (await travel.read_request(fresh)).revision,
                    "set": {
                        "city": "京都",
                        "adults": 2,
                        "child_ages": [],
                        "rooms": 1,
                        "start_date": "2026-11-03",
                        "end_date": "2026-11-05",
                        "transport": "transit",
                        "hard_constraints": ["住宿：无要求", "房型：无要求", "床型：无要求"],
                    },
                }
            ),
        )
        await goals(travel, fresh, "itinerary")
        # 用户说“这次想轻松点”：模型只改本次request，记忆抽取器也不提出长期偏好
        await travel.patch_request(
            fresh,
            RequestPatch.model_validate(
                {
                    "expected_revision": (await travel.read_request(fresh)).revision,
                    "set": {
                        "hard_constraints": [
                            "住宿：无要求",
                            "房型：无要求",
                            "床型：无要求",
                            "节奏：慢节奏",
                        ]
                    },
                }
            ),
        )
        staged = await stage(travel, fresh)
        assert staged.code is None and "memory_choices" not in staged.data
        assert await memory_cards(travel, fresh) == []
        assert await facts_by_key(travel, context.user_id) == before  # 长期偏好原封不动
        seen = {f["key"]: f["value"] for f in memory_of(await model_context(travel, fresh))}
        assert seen["pace"] == "特种兵"

    runner.run(exercise())


def test_conflicting_draft_and_missing_run_issue_no_merged_group(travel_setup: Setup) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        service, active = await answered_trip(travel, context, **ANSWERS)
        # 草稿尚未暂存：不发
        assert await ChoiceService(travel).merge_memory_cards(active) == []
        first, _ = await destinations(travel, active)
        closed = await TravelToolExecutor(travel).execute(
            active,
            "stage_plan_change",
            {
                "change": {
                    "kind": "initial",
                    "proposal": stage_proposal(first, closed=True).model_dump(mode="json"),
                }
            },
        )
        if closed.code is None and closed.data["validation"]["status"] == "conflict":  # type: ignore[index]
            assert "memory_choices" not in closed.data  # 冲突草稿不出偏好卡
            assert await memory_cards(travel, active) == []
        await service.cancel(context.user_id, active.run_id)
        await asyncio.gather(*tuple(service.tasks.values()))
        await service.close()

    runner.run(exercise())
