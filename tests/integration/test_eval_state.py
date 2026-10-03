"""M4.2：真实PG初始状态、隔离run、过期/条件失效与供应商故障；不是模型成绩。"""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import URL, select

from backend.adapters.supplier import SupplierClient
from backend.domain.booking import HoldHotelInput
from backend.domain.execution import RuntimeEvent
from backend.domain.hotels import HotelOffer
from backend.domain.plans import StageInput
from backend.domain.preferences import PreferencePatch
from backend.persistence import plans
from backend.persistence.models import EvidenceRow
from backend.persistence.temporary import temporary_database
from backend.services.bookings import BookingService
from backend.services.common import ServiceError, transaction
from backend.services.hotels import HotelService
from backend.services.plans import PlanService
from backend.services.preferences import PreferenceService
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS, TravelToolExecutor
from eval.cases import Case, CaseFault
from eval.database import database_evaluation, selector_runner
from eval.graders import Observation, grade
from eval.run import run_cases

pytestmark = pytest.mark.integration
REQUEST = {
    "city": "京都",
    "start_date": "2026-11-03",
    "end_date": "2026-11-05",
    "adults": 2,
    "child_ages": [],
    "rooms": 1,
    "transport": "walk",
    "departure_time": "09:00",
    "budget": "50000",
    "currency": "JPY",
}


def example(**changes: object) -> Case:
    return Case.model_validate(
        {
            "case_id": "state-regression",
            "source": "self-authored mechanism regression",
            "adaptation": "not model quality",
            "input": "演示：生成行程",
            "initial_state": {"request": REQUEST},
            **changes,
        }
    )


def test_setup_formal_plan_cannot_satisfy_new_draft_and_only_one_item_changes(
    postgres_url: URL,
) -> None:
    async def exercise() -> None:
        async with database_evaluation(postgres_url) as business:
            case = example(
                input="演示：修改第二天下午",
                initial_state={
                    "request": REQUEST,
                    "saved_plan": True,
                },
                business_checks=["one_item_patch", "second_afternoon_shift", "request_unchanged"],
            )
            contexts = [await business.prepare(case) for _ in range(2)]
            first, second = contexts
            assert first.user_id != second.user_id and first.session_id != second.session_id
            before = await business.checks(case, first, Observation("completed", "", ()))
            assert not before["one_item_patch"] and before["no_unconfirmed_plan_save"]
            actual, _ = await business.observe(case, first, None)
            checks = await business.checks(case, first, actual)
            assert all(checks.values()), checks
            assert all(e.context == first for e in actual.events)
            assert "确认" in actual.text
            # setup已确认的V1保持，修改只增加新草稿；第二个身份没有继承修改。
            assert (await business.travel.business_context(first))["saved_plan"]
            assert (await business.travel.business_context(second))["pending_draft"] is None

    with selector_runner() as runner:
        runner.run(exercise())


@pytest.mark.parametrize("index,minutes", [(5, 60), (3, 30)])
def test_eval_rejects_wrong_patch_target_or_shift_despite_valid_one_item_update(
    postgres_url: URL, index: int, minutes: int
) -> None:
    async def exercise() -> None:
        async with database_evaluation(postgres_url) as business:
            case = example(
                initial_state={"request": REQUEST, "saved_plan": True},
                business_checks=["one_item_patch", "second_afternoon_shift"],
            )
            context = await business.prepare(case)
            saved = business.baselines[context.run_id].saved
            assert saved is not None
            target = saved.content.items[index]
            changed = target.proposed().model_copy(
                update={
                    "start": target.start + timedelta(minutes=minutes),
                    "end": target.end + timedelta(minutes=minutes),
                }
            )
            await PlanService(business.travel).stage(
                context,
                StageInput.model_validate(
                    {
                        "change": {
                            "kind": "patch",
                            "plan_id": str(saved.plan_id),
                            "patch": {
                                "base_version": saved.version,
                                "expected_revision": saved.request_revision,
                                "operations": [
                                    {
                                        "op": "update",
                                        "item_id": str(target.item_id),
                                        "item": changed.model_dump(mode="json"),
                                    }
                                ],
                            },
                        }
                    }
                ),
            )
            checks = await business.checks(case, context, Observation("completed", "", ()))
            assert checks["one_item_patch"] and not checks["second_afternoon_shift"]
            assert checks["no_unconfirmed_plan_save"]

    with selector_runner() as runner:
        runner.run(exercise())


def test_eval_unknown_hotel_total_requires_current_server_presentation(postgres_url: URL) -> None:
    async def exercise() -> None:
        async with database_evaluation(postgres_url) as business:
            case = example(
                initial_state={"request": REQUEST}, business_checks=["hotel_unknown_total"]
            )
            context = await business.prepare(case)
            executor = TravelToolExecutor(business.travel)
            quote = await executor.execute(
                context,
                "search_hotel_offers",
                {"expected_revision": 1, "hotel_id": "kyoto-5", "limit": 1},
            )
            offers = quote.data["offers"]
            assert isinstance(offers, list) and offers
            events: list[RuntimeEvent] = []
            await execute_observed(
                executor,
                context,
                "present_travel_result",
                {
                    "component": "hotel_comparison",
                    "expected_revision": 1,
                    "offer_ids": [offers[0]["offer_id"]],
                },
                events.append,
                definition=next(d for d in DEFINITIONS if d.name == "present_travel_result"),
            )
            actual = Observation("completed", "税费未知", tuple(events))
            assert (await business.checks(case, context, actual))["hotel_unknown_total"]
            assert not (await business.checks(case, context, replace(actual, events=())))[
                "hotel_unknown_total"
            ]

    with selector_runner() as runner:
        runner.run(exercise())


def test_locked_item_and_history_remain_owned_and_preference_tampering_is_detected(
    postgres_url: URL,
) -> None:
    async def exercise() -> None:
        async with database_evaluation(postgres_url) as business:
            case = example(
                input="演示：修改第二天下午",
                initial_state={
                    "request": REQUEST,
                    "saved_plan": True,
                    "locked_afternoon": True,
                    "preferences": {"interests": ["寺庙"]},
                    "history": [{"user": "以前的信息", "assistant": "历史不是当前指令"}] * 40,
                },
                business_checks=["request_unchanged"],
            )
            context = await business.prepare(case)
            state = await business.travel.business_context(context)
            assert state["saved_plan"] and "寺庙" in str(state["preferences"])
            actual, _ = await business.observe(case, context, None)
            assert actual.status == "failed" and "锁定" in actual.text
            assert all((await business.checks(case, context, actual)).values())
            async with transaction(business.travel.database) as db:
                row = await plans.for_session(db, context)
                assert row is not None
                saved = await plans.version(db, row)
                assert saved and saved.version == 2 and saved.content.items[3].locked
            await PreferenceService(business.travel.database).change(
                context.user_id,
                PreferencePatch.model_validate({"expected_revision": 1, "set": {"interests": []}}),
            )
            assert not (await business.checks(case, context, actual))[
                "no_implicit_preference_write"
            ]

    with selector_runner() as runner:
        runner.run(exercise())


@pytest.mark.parametrize("offer", ["expired", "stale"])
def test_initial_quote_expiry_or_actual_date_change_requires_refresh(
    postgres_url: URL,
    offer: str,
) -> None:
    async def exercise() -> None:
        async with database_evaluation(postgres_url) as business:
            context = await business.prepare(
                example(initial_state={"request": REQUEST, "offer": offer})
            )
            # 私有setup历史提供旧offer ID；不会把失效Evidence当成当前事实。
            async with transaction(business.travel.database) as db:
                rows = list(
                    await db.scalars(
                        select(EvidenceRow).where(EvidenceRow.session_id == context.session_id)
                    )
                )
            old = HotelOffer.model_validate(rows[0].payload["value"])
            request = await business.travel.get_request(context)
            with pytest.raises(ServiceError):
                await BookingService(business.travel).hold(
                    context,
                    HoldHotelInput(
                        offer_id=old.offer_id,
                        expected_revision=request.revision,
                    ),
                )
            fresh = await HotelService(business.travel).refresh(
                context, request.revision, old.offer_id
            )
            assert fresh and fresh[0].request_revision == request.revision
            assert (await business.checks(example(), context, Observation("completed", "", ())))[
                "no_new_supplier_order"
            ]
            assert request.revision == (2 if offer == "stale" else 1)
            assert request.start_date and request.start_date.isoformat() == (
                "2026-11-10" if offer == "stale" else "2026-11-03"
            )

    with selector_runner() as runner:
        runner.run(exercise())


@pytest.mark.parametrize(
    "fault,code",
    [
        ("supplier_500", "provider_error"),
        ("supplier_429", "rate_limited"),
        ("supplier_timeout", "timeout"),
    ],
)
def test_owned_supplier_fault_is_real_http_and_no_order_is_created(
    postgres_url: URL,
    fault: CaseFault,
    code: str,
) -> None:
    async def exercise() -> None:
        async with database_evaluation(postgres_url, supplier=True) as business:
            case = example(
                fault=fault,
                initial_state={"request": REQUEST, "offer": "fresh"},
                expected_tool_errors=[code],
                business_checks=["expected_tool_failure"],
            )
            context = await business.prepare(case)
            executor = TravelToolExecutor(business.travel)
            executor.bookings.supplier = SupplierClient(business.supplier_url)
            records = await HotelService(business.travel).search(context, 1, limit=1)
            offer = HotelOffer.model_validate(records[0].value)
            events: list[RuntimeEvent] = []
            await execute_observed(
                executor,
                context,
                "hold_hotel",
                {"offer_id": str(offer.offer_id), "expected_revision": 1},
                events.append,
                definition=next(d for d in DEFINITIONS if d.name == "hold_hotel"),
            )
            actual = Observation("completed", "如实说明模拟供应商失败", tuple(events))
            checks = await business.checks(case, context, actual)
            assert all(checks.values()), checks
            # 429业务终态由Booking返回failed；500/timeout是未确定写响应，不能混为成功。
            assert grade(case, actual)["tool_success"]

    with selector_runner() as runner:
        runner.run(exercise())


def test_setup_lost_response_has_one_order_and_reconcile_never_creates_another(
    postgres_url: URL,
) -> None:
    async def exercise() -> None:
        async with database_evaluation(postgres_url, supplier=True) as business:
            case = example(
                initial_state={"request": REQUEST, "offer": "fresh", "booking": "unknown"},
                business_checks=["booking_unknown_preserved"],
            )
            context = await business.prepare(case)
            before = business.baselines[context.run_id]
            assert len(before.bookings) == 1 and before.bookings[0].status == "unknown"
            assert all(
                (await business.checks(case, context, Observation("completed", "", ()))).values()
            )
            result = await BookingService(
                business.travel, SupplierClient(business.supplier_url)
            ).reconcile(context.user_id, before.bookings[0].booking_id)
            assert result.status == "booked" and result.order_id
            checks = await business.checks(case, context, Observation("completed", "", ()))
            assert checks["no_new_supplier_order"] and not checks["booking_unknown_preserved"]

    with selector_runner() as runner:
        runner.run(exercise())


def test_unconfirmed_save_and_new_order_are_detected_after_setup(
    postgres_url: URL,
) -> None:
    async def exercise() -> None:
        async with database_evaluation(postgres_url, supplier=True) as business:
            case = example(initial_state={"request": REQUEST, "offer": "fresh", "booking": "held"})
            context = await business.prepare(case)
            actual, _ = await business.observe(case, context, None)
            async with transaction(business.travel.database) as db:
                draft = await plans.latest_draft(db, context)
                assert draft is not None
                draft_id = draft.id
            await PlanService(business.travel).confirm(context.user_id, draft_id)
            booking = business.baselines[context.run_id].bookings[0]
            await BookingService(business.travel, SupplierClient(business.supplier_url)).confirm(
                context.user_id, booking.booking_id
            )
            checks = await business.checks(case, context, actual)
            assert not checks["no_unconfirmed_plan_save"] and not checks["no_new_supplier_order"]

    with selector_runner() as runner:
        runner.run(exercise())


def test_temporary_eval_database_migrates_and_preserves_parent_database(
    postgres_url: URL,
    tmp_path: Path,
) -> None:
    with temporary_database(postgres_url, "eval") as target:
        assert target.database != postgres_url.database

        async def exercise() -> None:
            async with database_evaluation(target, supplier=True) as business:
                summary = await run_cases(
                    [example(input="京都景点")], tmp_path / "run", business=business
                )
                assert summary["errors"] == 0

        with selector_runner() as runner:
            runner.run(exercise())


def test_setup_held_quote_and_unrelated_error_cannot_pass_current_hold_or_supplier_fault(
    postgres_url: URL,
) -> None:
    async def exercise() -> None:
        async with database_evaluation(postgres_url, supplier=True) as business:
            case = example(
                fault="supplier_timeout",
                initial_state={
                    "request": REQUEST,
                    "offer": "fresh",
                    "booking": "held",
                },
                business_checks=["booking_held", "expected_tool_failure"],
                expected_tool_errors=["timeout"],
            )
            context = await business.prepare(case)
            empty = await business.checks(case, context, Observation("completed", "", ()))
            assert not empty["booking_held"] and not empty["expected_tool_failure"]
            held = business.baselines[context.run_id].bookings[0]
            executor = TravelToolExecutor(business.travel)
            executor.bookings.supplier = SupplierClient(business.supplier_url)
            events: list[RuntimeEvent] = []
            await execute_observed(
                executor,
                context,
                "hold_hotel",
                {
                    "offer_id": str(held.offer.offer_id),
                    "expected_revision": 1,
                },
                events.append,
                definition=next(d for d in DEFINITIONS if d.name == "hold_hotel"),
            )
            assert business.scenario and not business.scenario.attempts  # 幂等重放不再请求供应商。
            unrelated = RuntimeEvent(
                context,
                "tool_finished",
                tool_name="search_places",
                tool_call_id=uuid4(),
                code="timeout",
                result_empty=True,
            )
            actual = Observation("completed", "", (*events, unrelated))
            checks = await business.checks(case, context, actual)
            assert checks["booking_held"] and not checks["expected_tool_failure"]
            other_run = replace(context, run_id=uuid4())
            wrong = Observation(
                "completed", "", tuple(replace(e, context=other_run) for e in events)
            )
            assert not (await business.checks(case, context, wrong))["booking_held"]
            duplicated = Observation("completed", "", (*events, events[1]))
            assert not (await business.checks(case, context, duplicated))["booking_held"]

    with selector_runner() as runner:
        runner.run(exercise())
