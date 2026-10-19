"""R2：不加会话锁的读（read_request）之后紧跟写的调用点，写侧必须自己加锁并重验条件/revision。

做法：在“读之后、写之前”的缝隙里用 monkeypatch 注入并发写者（独立事务提交），
断言写侧要么拒绝（409）、要么至少不留下与新条件矛盾的可用数据。
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from backend.domain.evidence import EvidenceRecord
from backend.domain.execution import RunContext
from backend.domain.travel_request import RequestPatch
from backend.persistence.catalog import import_catalog
from backend.persistence.models import EvidenceRow
from backend.services.common import ServiceError, transaction
from backend.services.hotels import HotelService
from backend.services.travel import TravelService
from backend.tools.travel import TravelToolExecutor
from data.import_catalog import load_snapshot
from tests.integration.test_travel import travel_setup as travel_setup
from tests.integration.user_turn import start_turn

pytestmark = pytest.mark.integration

Setup = tuple[asyncio.Runner, TravelService, RunContext]


async def change(travel: TravelService, context: RunContext, fields: dict[str, object]) -> int:
    """独立事务里的并发写者；返回新revision。"""
    current = await travel.read_request(context)
    updated = await travel.patch_request(
        context,
        RequestPatch.model_validate({"expected_revision": current.revision, "set": fields}),
    )
    return updated.request.revision


def inject_before_record(
    monkeypatch: pytest.MonkeyPatch,
    travel: TravelService,
    after_read: Callable[[], Awaitable[None]],
) -> None:
    """让第一次record_evidence之前先跑一个并发写者（模拟读与写之间被抢先）。"""
    original = TravelService.record_evidence
    fired = False

    async def wrapper(
        self: TravelService, context: RunContext, records: Sequence[EvidenceRecord]
    ) -> None:
        nonlocal fired
        if not fired:
            fired = True
            await after_read()
        await original(self, context, records)

    monkeypatch.setattr(TravelService, "record_evidence", wrapper)


async def evidence_count(travel: TravelService, context: RunContext, kind: str) -> int:
    async with transaction(travel.database) as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(EvidenceRow)
                .where(EvidenceRow.session_id == context.session_id, EvidenceRow.kind == kind)
            )
            or 0
        )


def test_hotel_search_read_then_condition_change_does_not_store_stale_offers(
    travel_setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """读后、写证据前日期被并发改掉：record_evidence在锁内重验，409且不落任何旧日期报价。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        request = await travel.read_request(context)
        inject_before_record(
            monkeypatch,
            travel,
            lambda: change(travel, context, {"start_date": "2026-12-01", "end_date": "2026-12-03"}),  # type: ignore[arg-type,return-value]
        )
        with pytest.raises(ServiceError) as raised:
            await HotelService(travel).search(context, request.revision, limit=3)
        assert raised.value.status == 409
        assert await evidence_count(travel, context, "hotel_offer") == 0

    runner.run(exercise())


def test_hotel_tool_after_unrelated_change_reports_stale_revision_not_offers(
    travel_setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """读后、写前改了不入证据条件的字段（interests）：工具结果在锁外再读revision，必须报过期而非返回报价。"""
    runner, travel, context = travel_setup
    context_run = runner.run(start_turn(travel, context, "查酒店"))

    async def exercise() -> None:
        request = await travel.read_request(context_run)
        inject_before_record(
            monkeypatch,
            travel,
            lambda: change(travel, context_run, {"interests": ["美食"]}),  # type: ignore[arg-type,return-value]
        )
        result = await TravelToolExecutor(travel).execute(
            context_run,
            "search_hotel_offers",
            {"expected_revision": request.revision, "limit": 3},
        )
        assert result.code == "conflict" and not result.data.get("offers")

    runner.run(exercise())


def test_conversation_patch_with_stale_read_never_overwrites_concurrent_change(
    travel_setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ConversationRequestPatch先read_request做来源核对，再patch_request；核对与写之间被并发写者抢先时，
    写侧在锁内按expected_revision拒绝，并发写入的值保留，revision只前进一次。"""
    runner, travel, context = travel_setup
    context_run = runner.run(start_turn(travel, context, "3个人"))

    async def exercise() -> None:
        base = await travel.read_request(context_run)
        original = TravelService.trusted_user_text
        fired = False

        async def racing(self: TravelService, ctx: RunContext) -> str:
            nonlocal fired
            text = await original(self, ctx)
            if not fired:
                fired = True
                await change(travel, context_run, {"rooms": 2})
            return text

        monkeypatch.setattr(TravelService, "trusted_user_text", racing)
        result = await TravelToolExecutor(travel).execute(
            context_run,
            "update_travel_request",
            {
                "expected_revision": base.revision,
                "set": {"adults": 3},
                "explicit_fields": ["adults"],
            },
        )
        assert result.code == "conflict"
        after = await travel.read_request(context_run)
        assert after.revision == base.revision + 1
        assert after.rooms == 2 and after.adults == base.adults

    runner.run(exercise())


def test_catalog_search_read_then_city_change_stores_no_stale_place_evidence(
    travel_setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """catalog._load用read_request；读后城市被改，publish的record_evidence在锁内拒绝，不留旧城市地点证据。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        async with transaction(travel.database) as db:
            await import_catalog(db, load_snapshot())
        inject_before_record(
            monkeypatch,
            travel,
            lambda: change(travel, context, {"city": "大阪"}),  # type: ignore[arg-type,return-value]
        )
        result = await TravelToolExecutor(travel).execute(
            context, "search_places", {"city": "京都", "query": "清水寺", "limit": 1}
        )
        assert result.code == "conflict" and not result.evidence_ids
        assert await evidence_count(travel, context, "place") == 0

    runner.run(exercise())


def test_offer_found_before_hard_constraint_change_cannot_be_held_as_current(
    travel_setup: Setup,
) -> None:
    """hard_constraints/预算不在hotel_offer证据条件里：旧revision查到的报价在条件变化后不能当作当前报价暂留。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        from backend.domain.booking import HoldHotelInput
        from backend.domain.hotels import HotelOffer
        from backend.services.bookings import BookingService
        from mock_supplier.service import SupplierService

        request = await travel.read_request(context)
        records = await HotelService(travel).search(context, request.revision, limit=1)
        offer = HotelOffer.model_validate(records[0].value)
        revision = await change(
            travel, context, {"hard_constraints": ["住宿：无要求", "房型：和室", "床型：无要求"]}
        )
        service = BookingService(travel, SupplierService(travel.database))
        try:
            held = await service.hold(
                context, HoldHotelInput(offer_id=offer.offer_id, expected_revision=revision)
            )
        except ServiceError as error:
            assert error.status in {409, 422}
            return
        # 当前行为：旧报价仍被受理(证据条件不含hard_constraints)，但转held时发现
        # offer.request.revision过期，落成expired，用户侧永远不是held；供应商hold白占到自然过期。
        assert (
            held.status == "expired" and held.history[-1].reason == "conditions_changed_during_hold"
        )

    runner.run(exercise())


def test_concurrent_search_and_date_change_leave_no_applicable_stale_offer(
    travel_setup: Setup,
) -> None:
    """真并发：酒店搜索与改日期同时进行多轮；结束后任何仍“适用于当前条件”的报价证据都必须是当前日期的。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        windows = [("2026-11-10", "2026-11-12"), ("2026-11-03", "2026-11-05")]
        for round_ in range(20):
            start, end = windows[round_ % 2]
            request = await travel.read_request(context)
            results = await asyncio.gather(
                HotelService(travel).search(context, request.revision, limit=2),
                change(travel, context, {"start_date": start, "end_date": end}),
                return_exceptions=True,
            )
            for r in results:
                assert not isinstance(r, BaseException) or isinstance(r, ServiceError), r
            current = await travel.read_request(context)
            async with transaction(travel.database) as db:
                rows = (
                    await db.scalars(
                        select(EvidenceRow).where(
                            EvidenceRow.session_id == context.session_id,
                            EvidenceRow.kind == "hotel_offer",
                        )
                    )
                ).all()
            from backend.persistence.travel import evidence_from_row

            now = datetime.now(UTC)
            for row in rows:
                record = evidence_from_row(row)
                if record.applicable(current, now):
                    assert record.conditions["start_date"] == current.start_date.isoformat()  # type: ignore[union-attr]

    runner.run(exercise())


def test_lock_free_reads_are_not_used_by_write_paths() -> None:
    """守卫：已知会写的服务方法不得直接用read_request（它们必须经owned_request加锁）。"""
    import inspect

    from backend.services import bookings, plans

    for fn in (
        bookings.BookingService.hold,
        bookings.BookingService._update,
        bookings.BookingService.confirm,
        plans.PlanService.confirm,
        plans.PlanService.locks,
        TravelService.patch_request_in_transaction,
        TravelService.record_evidence,
        TravelService.business_context,
    ):
        assert "read_request" not in inspect.getsource(fn), fn.__qualname__
