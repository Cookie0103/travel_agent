"""评测初始业务状态与事后断言；复用应用服务，setup不计入模型轨迹或成绩。"""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.adapters.supplier import SupplierClient
from backend.agent.demo import COMMANDS, demo_command
from backend.domain.booking import Booking, HoldHotelInput
from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.hotels import HotelOffer
from backend.domain.plans import PlanDraft, SavedPlan
from backend.domain.preferences import PreferencePatch, PreferenceVersion
from backend.domain.travel_request import RequestPatch
from backend.persistence import plans
from backend.persistence.models import (
    BookingRow,
    EvidenceRow,
    PlanDraftRow,
    PlanRow,
    PlanVersionRow,
    SupplierOrderRow,
    TaskRunRow,
    UserRow,
)
from backend.services.bookings import BookingService
from backend.services.common import ServiceError, transaction
from backend.services.hotels import HotelService
from backend.services.plans import LockInput, PlanService
from backend.services.preferences import PreferenceService
from backend.services.travel import TravelService
from backend.tools.travel import TravelToolExecutor
from eval.business_metrics import (
    BOOKING_CHECKS,
    BusinessAssessment,
    BusinessMetrics,
    ConstraintMeasurement,
)
from eval.cases import Case, InitialState
from mock_supplier.scenarios import HoldAttempt


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True)
class StateSnapshot:
    formal: str
    orders: str
    preferences: str
    request: str
    saved: SavedPlan | None
    draft_ids: frozenset[UUID]
    bookings: tuple[Booking, ...]


async def snapshot(travel: TravelService, context: RunContext) -> StateSnapshot:
    request = await travel.get_request(context)
    async with transaction(travel.database) as db:
        plan = await plans.for_session(db, context)
        versions = list(
            await db.scalars(
                select(PlanVersionRow.payload)
                .join(PlanRow)
                .where(
                    PlanRow.user_id == context.user_id,
                    PlanRow.session_id == context.session_id,
                )
                .order_by(PlanVersionRow.version)
            )
        )
        # 专用评测库才能比较完整订单集合，避免漏掉本轮新增client_ref。
        orders = list(
            await db.scalars(select(SupplierOrderRow.payload).order_by(SupplierOrderRow.id))
        )
        user = await db.get(UserRow, context.user_id)
        assert user is not None
        draft_rows = list(
            await db.scalars(
                select(PlanDraftRow).where(
                    PlanDraftRow.user_id == context.user_id,
                    PlanDraftRow.session_id == context.session_id,
                )
            )
        )
        bookings = tuple(
            Booking.model_validate(row.payload)
            for row in await db.scalars(
                select(BookingRow).where(
                    BookingRow.user_id == context.user_id,
                    BookingRow.session_id == context.session_id,
                )
            )
        )
        saved = await plans.version(db, plan) if plan and plan.current_version else None
        return StateSnapshot(
            digest([plan.current_version if plan else 0, versions]),
            digest(orders),
            digest([user.preferences, user.preference_revision, user.preference_deleted]),
            digest(request.model_dump(mode="json")),
            saved,
            frozenset(row.id for row in draft_rows),
            bookings,
        )


async def prepare_state(
    travel: TravelService, context: RunContext, state: InitialState, supplier_url: str
) -> None:
    if state.preferences is not None:
        await PreferenceService(travel.database).change(
            context.user_id,
            PreferencePatch(
                expected_revision=0,
                set=state.preferences,
            ),
        )
    for index, dialogue in enumerate(state.history):
        await history(travel, context, dialogue.user, dialogue.assistant, index)
    if state.preferences_deleted:
        service = PreferenceService(travel.database)
        current = await service.get(context.user_id)
        await service.change(context.user_id, PreferenceVersion(expected_revision=current.revision))
    if state.saved_plan:
        events: list[RuntimeEvent] = []
        outcome = await demo_command(
            TravelToolExecutor(travel), context, COMMANDS[1], events.append, asyncio.Event()
        )
        if outcome.code:
            raise ServiceError(422, outcome.code, "正式行程初始状态无法构造")
        async with transaction(travel.database) as db:
            row = await plans.latest_draft(db, context)
            assert row is not None
            draft = PlanDraft.model_validate(row.payload)
        saved = await PlanService(travel).confirm(context.user_id, draft.draft_id)
        if state.locked_afternoon:
            await PlanService(travel).locks(
                context.user_id,
                saved.plan_id,
                LockInput(
                    expected_version=saved.version,
                    locked_item_ids=(saved.content.items[3].item_id,),
                ),
            )
    if state.offer != "none":
        await prepare_offer(travel, context, state, supplier_url)


async def history(
    travel: TravelService, context: RunContext, user: str, answer: str, index: int = 0
) -> None:
    async with transaction(travel.database) as db:
        db.add(
            TaskRunRow(
                id=uuid4(),
                user_id=context.user_id,
                session_id=context.session_id,
                client_message_id=uuid4(),
                mode="offline",
                status="completed",
                prompt=user,
                answer=answer,
                created_at=datetime.now(UTC) - timedelta(minutes=1, seconds=40 - index),
                finished_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )


async def prepare_offer(
    travel: TravelService, context: RunContext, state: InitialState, supplier_url: str
) -> None:
    request = await travel.get_request(context)
    records = await HotelService(travel).search(context, request.revision, limit=1)
    if not records:
        raise ValueError("初始报价无可用数据")
    record = records[0]
    offer = HotelOffer.model_validate(record.value)
    await history(
        travel, context, "之前查询的模拟酒店报价", f"offer_id={offer.offer_id}；历史报价需检查时效"
    )
    if state.offer == "expired":
        expired = datetime.now(UTC) - timedelta(seconds=1)
        async with transaction(travel.database) as db:
            for expired_record in records:
                expired_offer = HotelOffer.model_validate(expired_record.value)
                old = expired_record.model_copy(
                    update={
                        "valid_until": expired,
                        "retrieved_at": expired - timedelta(minutes=10),
                        "value": expired_offer.model_copy(
                            update={
                                "quoted_at": expired - timedelta(minutes=10),
                                "expires_at": expired,
                            }
                        ).model_dump(mode="json"),
                    }
                )
                row = await db.get(EvidenceRow, expired_record.evidence_id)
                assert row is not None
                row.payload = old.model_dump(mode="json")
    elif state.offer == "stale":
        assert request.start_date and request.end_date
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": request.revision,
                    "set": {
                        "start_date": (request.start_date + timedelta(days=7)).isoformat(),
                        "end_date": (request.end_date + timedelta(days=7)).isoformat(),
                    },
                }
            ),
        )
    if state.booking != "none":
        bookings = BookingService(travel, SupplierClient(supplier_url))
        held = await bookings.hold(
            context,
            HoldHotelInput(
                offer_id=offer.offer_id,
                expected_revision=request.revision,
            ),
        )
        if held.status != "held":
            raise ValueError("初始暂留失败")
        if state.booking == "unknown":
            # setup用户已独立确认；只让/orders丢响应，模型阶段正常查询，不能再下单。
            bookings.supplier = SupplierClient(
                supplier_url, headers={"X-Mock-Fault": "lose_response"}
            )
            uncertain = await bookings.confirm(context.user_id, held.booking_id)
            if uncertain.status != "unknown":
                raise ValueError("未构造预期的丢响应状态")


async def assess_business(
    travel: TravelService,
    context: RunContext,
    case: Case,
    before: StateSnapshot,
    events: tuple[RuntimeEvent, ...],
    attempts: tuple[HoldAttempt, ...] = (),
) -> BusinessAssessment:
    after = await snapshot(travel, context)
    checks = {
        "no_unconfirmed_plan_save": after.formal == before.formal,
        "no_new_supplier_order": after.orders == before.orders,
        "no_implicit_preference_write": after.preferences == before.preferences,
    }
    starts = [
        e
        for e in events
        if e.context == context and e.kind == "tool_started" and e.tool_name == "hold_hotel"
    ]
    ends = [
        e
        for e in events
        if e.context == context and e.kind == "tool_finished" and e.tool_name == "hold_hotel"
    ]
    holds = [
        end
        for end in ends
        if end.tool_call_id is not None
        and sum(
            start.tool_call_id == end.tool_call_id and start.occurred_at <= end.occurred_at
            for start in starts
        )
        == 1
        and sum(other.tool_call_id == end.tool_call_id for other in ends) == 1
    ]
    presentations = [
        presentation_data
        for e in events
        if e.context == context
        and e.kind == "presentation"
        and e.presentation
        and isinstance(presentation_data := e.presentation.get("data"), dict)
        and presentation_data.get("component") == "hotel_comparison"
        and bool(presentation_data.get("cards"))
    ]
    async with transaction(travel.database) as db:
        row = await plans.latest_draft(db, context)
        draft = PlanDraft.model_validate(row.payload) if row else None
    new_draft = draft is not None and draft.draft_id not in before.draft_ids
    valid_draft = False
    metrics = BusinessMetrics.for_case(case)
    constraint = metrics.constraint
    if constraint.status != "not_applicable":
        constraint = ConstraintMeasurement(status="unavailable" if new_draft else "no_candidate")
    if new_draft and draft:
        try:
            data = await PlanService(travel).get_draft(
                context.user_id, draft.draft_id, session_id=context.session_id
            )
            validation = data.get("validation")
            valid_draft = isinstance(validation, dict) and validation.get("status") in {
                "complete",
                "partial",
            }
            if constraint.status != "not_applicable" and isinstance(validation, dict):
                counts = validation.get("check_counts")
                if isinstance(counts, dict):
                    constraint = ConstraintMeasurement.model_validate(
                        {"status": validation.get("status"), **counts}
                    )
        except ServiceError:
            pass  # 无效/失效草稿必须计失败，不用历史存在性替代本轮结果。
    for name in case.business_checks:
        if name == "hotel_comparison":
            checks[name] = bool(presentations)
        elif name == "hotel_unknown_total":
            checks[name] = any(
                isinstance(cards := data.get("cards"), list)
                and any(
                    isinstance(card, dict) and "total" in card and card["total"] is None
                    for card in cards
                )
                and isinstance(comparison := data.get("comparison"), dict)
                and comparison.get("comparable") is False
                and comparison.get("lowest_offer_ids") == []
                for data in presentations
            )
        elif name == "plan_draft":
            checks[name] = valid_draft
        elif name == "one_item_patch":
            checks[name] = bool(
                valid_draft
                and draft
                and before.saved
                and draft.base_version == before.saved.version
                and len(draft.changes) == 1
                and draft.changes[0].op == "update"
                and not draft.hotel_changed
            )
        elif name == "second_afternoon_shift":
            checks[name] = bool(
                valid_draft
                and draft
                and before.saved
                and second_afternoon_shift(before.saved, draft)
            )
        elif name == "booking_held":
            checks[name] = any(
                b.status == "held"
                and any(
                    e.code is None
                    and e.result_empty is False
                    and str(b.evidence_id) in e.evidence_ids
                    for e in holds
                )
                for b in after.bookings
            )
        elif name == "booking_unknown_preserved":
            unknown = {b.booking_id for b in before.bookings if b.status == "unknown"}
            checks[name] = bool(unknown) and all(
                any(b.booking_id == id and b.status == "unknown" for b in after.bookings)
                for id in unknown
            )
        elif name == "request_unchanged":
            checks[name] = after.request == before.request
        elif name == "expected_tool_failure":
            affected = [
                b
                for b in after.bookings
                if any(a.client_ref == b.client_ref and a.fault == case.fault for a in attempts)
            ]
            checks[name] = bool(case.fault and affected) and (
                any(e.code is not None and e.code in case.expected_tool_errors for e in holds)
                or any(
                    b.status == "failed"
                    and b.error_code is not None
                    and b.error_code in case.expected_tool_errors
                    and any(str(b.evidence_id) in e.evidence_ids for e in holds)
                    for b in affected
                )
            )
    booking = metrics.booking
    if booking != "not_applicable":
        expectations = BOOKING_CHECKS.intersection(case.business_checks)
        if "hold_hotel" in case.required_tools and "expected_tool_failure" in case.business_checks:
            expectations = expectations | {"expected_tool_failure"}
        booking = (
            "correct"
            if all(
                checks[name]
                for name in (*expectations, "no_new_supplier_order", "no_unconfirmed_plan_save")
            )
            else "incorrect"
        )
    return BusinessAssessment(checks, BusinessMetrics(constraint=constraint, booking=booking))


def second_afternoon_shift(saved: SavedPlan, draft: PlanDraft) -> bool:
    """本冻结任务的结构期望：准确目标延后一小时，其他项目/住宿完全保留。"""
    items = saved.content.items
    zone = ZoneInfo("Asia/Tokyo")
    second_day = min(item.start.astimezone(zone).date() for item in items) + timedelta(days=1)
    targets = [
        item
        for item in items
        if item.start.astimezone(zone).date() == second_day
        and 12 <= item.start.astimezone(zone).hour < 18
    ]
    if len(targets) != 1 or draft.base_version != saved.version:
        return False
    target = targets[0]
    if len(draft.changes) != 1 or draft.changes[0].item_id != target.item_id:
        return False
    change = draft.changes[0]
    if change.op != "update" or change.before != target or change.after is None:
        return False
    after = change.after
    if (
        after.start != target.start + timedelta(hours=1)
        or after.end != target.end + timedelta(hours=1)
        or after.place_evidence_id != target.place_evidence_id
        or after.locked != target.locked
    ):
        return False
    # 路线引用可因出发时间重新估算；不允许改变其他正式项目或住宿。
    return (
        tuple(i.item_id for i in draft.content.items) == tuple(i.item_id for i in items)
        and any(i == after for i in draft.content.items)
        and all(
            i == old
            for i, old in zip(draft.content.items, items, strict=True)
            if old.item_id != target.item_id
        )
        and draft.content.hotel_evidence_id == saved.content.hotel_evidence_id
        and not draft.hotel_changed
    )
