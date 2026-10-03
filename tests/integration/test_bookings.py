"""R09–R11/R16：真实PG预订确认、幂等、身份、过期、依赖故障与对账。"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import URL, func, select, update

from backend.adapters.supplier import SupplierClient, SupplierError
from backend.api.app import create_app as create_travel_app
from backend.domain.booking import (
    Booking,
    HoldHotelInput,
    OrderInput,
    SupplierOrder,
    transition,
)
from backend.domain.execution import RunContext
from backend.domain.hotels import HotelOffer
from backend.domain.travel_request import RequestPatch
from backend.persistence.database import Database
from backend.persistence.models import BookingRow, SupplierHoldRow, SupplierOrderRow
from backend.services.bookings import BookingService
from backend.services.common import ServiceError
from backend.services.hotels import HotelService
from backend.services.sessions import SessionService
from backend.services.travel import TravelService
from backend.tools.travel import TravelToolExecutor
from mock_supplier.app import create_app
from mock_supplier.service import SupplierService
from tests.integration.http_helper import serve_http
from tests.integration.test_sessions import login
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


async def select_offer(travel: TravelService, context: RunContext) -> HoldHotelInput:
    request = await travel.get_request(context)
    records = await HotelService(travel).search(context, request.revision, limit=1)
    offer = HotelOffer.model_validate(records[0].value)
    return HoldHotelInput(offer_id=offer.offer_id, expected_revision=request.revision)


def test_hold_tool_never_orders_and_concurrent_user_confirm_books_once(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        supplier = SupplierService(travel.database)
        service = BookingService(travel, supplier)
        executor = TravelToolExecutor(travel)
        executor.bookings = service
        body = await select_offer(travel, context)
        held = await executor.execute(context, "hold_hotel", body.model_dump(mode="json"))
        assert held.code is None and held.data["status"] == "held"
        identity = UUID(str(held.data["booking_id"]))
        assert (await supplier.lookup(identity)).order is None
        for name in ("book_hotel", "confirm_booking", "save_booking"):
            result = await executor.execute(
                context, name, {"booking_id": str(identity), "user_confirmed": True}
            )
            assert result.code == "blocked"
        assert (await supplier.lookup(identity)).order is None
        with pytest.raises(ServiceError, match="预订不存在"):
            await service.confirm(uuid4(), identity)
        repeated = await service.hold(context, body)
        assert repeated.booking_id == identity
        await asyncio.gather(*(service.confirm(context.user_id, identity) for _ in range(3)))
        saved = await service.get(context.user_id, identity)
        assert saved.status == "booked" and saved.order_id
        assert await service.confirm(context.user_id, identity) == saved
        assert [event.status for event in saved.history][:3] == ["quoted", "held", "confirmed"]
        assert (await service.list(context))[0] == saved
        async with travel.database.sessions.begin() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(SupplierOrderRow)
                    .where(
                        SupplierOrderRow.client_ref == identity,
                    )
                )
                == 1
            )

    runner.run(exercise())


def test_long_valid_conditions_keep_hold_result_bounded_and_recoverable(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {
                        "interests": ["景" * 200] * 20,
                        "soft_constraints": ["慢" * 200] * 20,
                        "hard_constraints": ["休" * 200] * 20,
                    },
                }
            ),
        )
        executor = TravelToolExecutor(travel)
        executor.bookings.supplier = SupplierService(travel.database)
        body = await select_offer(travel, context)
        for _ in range(2):
            result = await executor.execute(context, "hold_hotel", body.model_dump(mode="json"))
            assert result.code is None and result.data["status"] == "held"
            assert len(json.dumps(result.payload(), ensure_ascii=False)) < 8000
            saved = await executor.bookings.get(
                context.user_id, UUID(str(result.data["booking_id"]))
            )
            assert saved.hold_id and saved.offer.request.interests == ("景" * 200,) * 20
            assert result.data["offer"] == saved.offer.card()

    runner.run(exercise())


def test_booking_restore_does_not_hide_active_records_behind_fifty_old_bookings(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        service = BookingService(travel, SupplierService(travel.database))
        for _ in range(51):
            records = await HotelService(travel).search(context, 1, limit=1)
            record = records[0]
            assert record.source_ref
            quoted = Booking.quoted(
                context.session_id,
                record.evidence_id,
                HotelOffer.model_validate(record.value),
                record.source_ref,
                record.content_version,
            )
            failed = transition(quoted, "failed", "historical_test_failure")
            async with travel.database.sessions.begin() as db:
                db.add(
                    BookingRow(
                        id=failed.booking_id,
                        user_id=context.user_id,
                        session_id=context.session_id,
                        evidence_id=record.evidence_id,
                        payload=failed.model_dump(mode="json"),
                    )
                )
        held = await service.hold(context, await select_offer(travel, context))
        rows = await BookingService(travel).list(context)
        assert len(rows) == 52 and rows[0] == held
        assert all(row.status == "failed" for row in rows[1:])
        assert (await service.confirm(context.user_id, held.booking_id)).status == "booked"
        assert (await BookingService(travel).list(context))[0].status == "booked"

    runner.run(exercise())


def test_hold_rejects_forgery_tax_unknown_and_changed_conditions_confirm(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        service = BookingService(travel, SupplierService(travel.database))
        with pytest.raises(ServiceError, match="不存在"):
            await service.hold(context, HoldHotelInput(offer_id=uuid4(), expected_revision=1))
        request = await travel.get_request(context)
        records = await HotelService(travel).search(context, request.revision, limit=6)
        unknown = next(
            HotelOffer.model_validate(row.value)
            for row in records
            if HotelOffer.model_validate(row.value).total is None
        )
        with pytest.raises(ServiceError, match="税费缺失"):
            await service.hold(
                context, HoldHotelInput(offer_id=unknown.offer_id, expected_revision=1)
            )
        held = await service.hold(context, await select_offer(travel, context))
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {"rooms": 2},
                }
            ),
        )
        with pytest.raises(ServiceError, match="条件已变化"):
            await service.confirm(context.user_id, held.booking_id)
        assert (await service.get(context.user_id, held.booking_id)).status == "held"
        assert (await SupplierService(travel.database).lookup(held.client_ref)).order is None

    runner.run(exercise())


def test_expired_hold_cannot_confirm_and_quote_expiry_does_not_shorten_valid_hold(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        service = BookingService(travel, SupplierService(travel.database))
        held = await service.hold(context, await select_offer(travel, context))
        async with travel.database.sessions.begin() as db:
            row = await db.get(BookingRow, held.booking_id)
            assert row is not None
            expired = held.model_copy(
                update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
            )
            row.payload = expired.model_dump(mode="json")
        assert (await service.confirm(context.user_id, held.booking_id)).status == "expired"
        assert (await service.get(context.user_id, held.booking_id)).history[
            -1
        ].reason == "hold_expired"
        other = await service.hold(context, await select_offer(travel, context))
        async with travel.database.sessions.begin() as db:
            row = await db.get(BookingRow, other.booking_id)
            assert row is not None
            # 已有效hold锁价15分钟，原5分钟quote到期不应缩短hold。
            old_offer = other.offer.model_copy(
                update={
                    "quoted_at": datetime.now(UTC) - timedelta(minutes=6),
                    "expires_at": datetime.now(UTC) - timedelta(minutes=1),
                }
            )
            row.payload = other.model_copy(update={"offer": old_offer}).model_dump(mode="json")
        assert (await service.confirm(context.user_id, other.booking_id)).status == "booked"

    runner.run(exercise())


class RateLimitedSupplier(SupplierService):
    def __init__(self, database: Database, *, failures: int, wait: float = 0.01) -> None:
        super().__init__(database)
        self.failures, self.wait, self.attempts = failures, wait, 0

    async def order(self, body: OrderInput) -> SupplierOrder:
        self.attempts += 1
        if self.attempts <= self.failures:
            raise SupplierError("rate_limited", retry_after=self.wait)
        return await super().order(body)


@pytest.mark.parametrize(
    "failures,wait,expected,attempts",
    [
        (2, 0.01, "booked", 3),
        (4, 0.01, "failed", 3),
        (4, 200.0, "failed", 1),
        (4, float("nan"), "failed", 1),
        (4, -1.0, "failed", 1),
    ],
)
def test_rate_limit_retries_are_bounded(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    failures: int,
    wait: float,
    expected: str,
    attempts: int,
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        supplier = RateLimitedSupplier(travel.database, failures=failures, wait=wait)
        service = BookingService(travel, supplier)
        held = await service.hold(context, await select_offer(travel, context))
        result = await service.confirm(context.user_id, held.booking_id)
        assert result.status == expected and supplier.attempts == attempts
        assert (await service.confirm(context.user_id, held.booking_id)) == result
        assert supplier.attempts == attempts

    runner.run(exercise())


def test_real_http_lost_order_response_reconciles_after_service_restart(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    with serve_http(create_app(Database(travel.database.engine.url), faults_enabled=True)) as url:

        async def exercise() -> None:
            client = SupplierClient(url)
            service = BookingService(travel, client)
            held = await service.hold(context, await select_offer(travel, context))
            client.headers = {"X-Mock-Fault": "lose_response"}
            result = await service.confirm(context.user_id, held.booking_id)
            assert result.status == "unknown" and result.order_id is None
            client.headers = {"X-Mock-Fault": "server_error"}
            assert (await service.reconcile(context.user_id, held.booking_id)).status == "unknown"
            restarted = BookingService(travel, SupplierClient(url))
            final = await restarted.confirm(context.user_id, held.booking_id)
            assert final.status == "booked" and final.order_id
            assert [event.status for event in final.history] == [
                "quoted",
                "held",
                "confirmed",
                "unknown",
                "booked",
            ]
            assert await restarted.confirm(context.user_id, held.booking_id) == final

        runner.run(exercise())


class UnknownSupplier(SupplierService):
    async def order(self, body: OrderInput) -> SupplierOrder:
        raise SupplierError("timeout", ambiguous=True)


def test_unknown_empty_lookup_stays_unknown_until_expired_hold_proves_absence(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        service = BookingService(travel, UnknownSupplier(travel.database))
        held = await service.hold(context, await select_offer(travel, context))
        assert (await service.confirm(context.user_id, held.booking_id)).status == "unknown"
        assert (await service.confirm(context.user_id, held.booking_id)).status == "unknown"
        async with travel.database.sessions.begin() as db:
            await db.execute(
                update(SupplierHoldRow)
                .where(
                    SupplierHoldRow.client_ref == held.client_ref,
                )
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        assert (await service.reconcile(context.user_id, held.booking_id)).status == "failed"

    runner.run(exercise())


def test_booking_http_user_confirmation_and_recovery_are_private(postgres_url: URL) -> None:
    sessions = SessionService(postgres_url, demo_enabled=True)
    travel = TravelService(sessions.database)
    service = BookingService(travel, SupplierService(sessions.database))
    options = {"loop_factory": asyncio.SelectorEventLoop}
    with TestClient(
        create_travel_app(sessions, booking_service=service), backend_options=options
    ) as client:
        owner, other = login(client), login(client)
        sid = client.post("/sessions", headers=owner).json()["session_id"]
        client.patch(
            f"/sessions/{sid}/request",
            headers=owner,
            json={
                "expected_revision": 0,
                "set": {
                    "city": "京都",
                    "start_date": "2026-11-03",
                    "end_date": "2026-11-05",
                    "adults": 2,
                    "child_ages": [],
                    "rooms": 1,
                },
            },
        )
        assert client.portal is not None
        identity = client.portal.call(sessions.authenticate, owner["Authorization"])
        selected = client.portal.call(select_offer, travel, RunContext(identity, UUID(sid)))
        path = f"/sessions/{sid}/hotel-holds"
        body = selected.model_dump(mode="json")
        assert client.post(path, headers=other, json=body).status_code == 404
        assert (
            client.post(path, headers=owner, json={**body, "user_confirmed": True}).status_code
            == 422
        )
        assert (
            client.post(path, headers=owner, json={**body, "expected_revision": -1}).status_code
            == 422
        )
        held = client.post(path, headers=owner, json=body)
        assert held.status_code == 200, held.text
        booking_path = "/bookings/" + held.json()["booking_id"]
        assert client.get(booking_path, headers=other).status_code == 404
        assert client.post(booking_path + "/confirm", headers=other).status_code == 404
        assert client.post(booking_path + "/reconcile", headers=other).status_code == 404
        assert client.get(f"/sessions/{sid}/bookings", headers=other).status_code == 404
        assert client.get(booking_path, headers=owner).json()["status"] == "held"
        saved = client.post(booking_path + "/confirm", headers=owner)
        assert saved.status_code == 200 and saved.json()["status"] == "booked", saved.text
        assert client.post(booking_path + "/confirm", headers=owner).json() == saved.json()
        assert client.post(path, headers=owner, json=body).json() == saved.json()
    with TestClient(
        create_travel_app(SessionService(postgres_url)), backend_options=options
    ) as restarted:
        assert restarted.get(booking_path, headers=owner).json() == saved.json()
        assert restarted.get(f"/sessions/{sid}/bookings", headers=owner).json() == [saved.json()]
