"""R09–R11：真实PG供应商幂等、过期和四种HTTP故障；不调用模型。"""

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import URL, func, select, update

from backend.domain.booking import HoldInput, OrderInput, SupplierHold, SupplierOrder
from backend.domain.execution import RunContext
from backend.domain.hotels import quote
from backend.domain.travel_request import TravelRequest
from backend.persistence.database import Database
from backend.persistence.models import SupplierHoldRow, SupplierOrderRow
from backend.providers.hotel_fixture import load_rates
from backend.services.common import ServiceError
from backend.services.travel import TravelService
from mock_supplier.app import create_app
from mock_supplier.service import SupplierService
from tests.integration.http_helper import serve_http
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


def test_supplier_concurrent_hold_order_and_restart_return_same_records(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        offer = quote(load_rates()[0][0], await travel.get_request(context), datetime.now(UTC))
        assert offer is not None
        body = HoldInput(client_ref=uuid4(), offer=offer)
        service = SupplierService(travel.database)
        first, second = await asyncio.gather(service.hold(body), service.hold(body))
        assert first == second
        order_input = OrderInput(client_ref=body.client_ref, hold_id=first.hold_id)
        orders = await asyncio.gather(*(service.order(order_input) for _ in range(3)))
        assert orders[0] == orders[1] == orders[2]
        restarted = SupplierService(travel.database)
        assert await restarted.order(order_input) == orders[0]
        assert (await restarted.lookup(body.client_ref)).order == orders[0]
        with pytest.raises(ServiceError, match="另一个报价"):
            await service.hold(
                body.model_copy(update={"offer": offer.model_copy(update={"offer_id": uuid4()})})
            )
        with pytest.raises(ServiceError, match="不存在"):
            await service.order(order_input.model_copy(update={"hold_id": uuid4()}))
        async with travel.database.sessions.begin() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(SupplierOrderRow)
                    .where(
                        SupplierOrderRow.client_ref == body.client_ref,
                    )
                )
                == 1
            )

    runner.run(exercise())


def test_supplier_rejects_incomplete_forged_expired_quote_and_expired_hold(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        now = datetime.now(UTC)
        offer = quote(load_rates()[0][0], await travel.get_request(context), now)
        assert offer is not None
        service = SupplierService(travel.database)
        for changes in (
            {"tax_amount": None},
            {"base_amount": Decimal("1")},
            {"quoted_at": now - timedelta(hours=1), "expires_at": now - timedelta(minutes=1)},
            {"quoted_at": now + timedelta(minutes=1), "expires_at": now + timedelta(minutes=2)},
            {"quoted_at": now - timedelta(days=1), "expires_at": now + timedelta(days=365)},
        ):
            body = HoldInput(client_ref=uuid4(), offer=offer.model_copy(update=changes))
            with pytest.raises(ServiceError, match="报价"):
                await service.hold(body)
        held = await service.hold(HoldInput(client_ref=uuid4(), offer=offer))
        before = await service.lookup(held.client_ref)
        assert before.order is None and not before.absence_final
        async with travel.database.sessions.begin() as db:
            await db.execute(
                update(SupplierHoldRow)
                .where(
                    SupplierHoldRow.client_ref == held.client_ref,
                )
                .values(expires_at=now - timedelta(seconds=1))
            )
        with pytest.raises(ServiceError, match="过期"):
            await service.order(OrderInput(client_ref=held.client_ref, hold_id=held.hold_id))
        assert (await service.lookup(held.client_ref)).absence_final
        assert not (await service.lookup(uuid4())).absence_final

    runner.run(exercise())


def test_supplier_http_faults_and_lost_response_leave_one_persisted_order(
    postgres_url: URL,
) -> None:
    from backend.domain.travel_request import TravelRequest

    offer = quote(
        load_rates()[0][0],
        TravelRequest.model_validate(
            {
                "city": "京都",
                "start_date": "2026-11-03",
                "end_date": "2026-11-05",
                "adults": 2,
                "child_ages": [],
                "rooms": 1,
            }
        ),
        datetime.now(UTC),
    )
    assert offer is not None
    body = HoldInput(client_ref=uuid4(), offer=offer).model_dump(mode="json")
    options = {"loop_factory": asyncio.SelectorEventLoop}
    with TestClient(
        create_app(Database(postgres_url), faults_enabled=True), backend_options=options
    ) as client:
        for fault, status in (("rate_limit", 429), ("server_error", 500)):
            response = client.post("/holds", json=body, headers={"X-Mock-Fault": fault})
            assert response.status_code == status
            if status == 429:
                assert response.headers["Retry-After"] == "1"
        assert (
            client.post("/holds", json=body, headers={"X-Mock-Fault": "invalid"}).status_code == 422
        )
        assert client.post("/holds", json=body, headers={"X-Mock-Delay": "-1"}).status_code == 422
        assert client.post("/holds", json={"client_ref": str(uuid4())}).status_code == 422
        response = client.post(
            "/holds", json=body, headers={"X-Mock-Fault": "delay", "X-Mock-Delay": "0.01"}
        )
        assert response.status_code == 201, response.text
        hold = SupplierHold.model_validate(response.json())
        order = {"client_ref": str(hold.client_ref), "hold_id": str(hold.hold_id)}
        with pytest.raises(ConnectionError, match="传输中断"):
            client.post("/orders", json=order, headers={"X-Mock-Fault": "lose_response"})
        lookup = client.get("/orders", params={"client_ref": str(hold.client_ref)}).json()
        assert lookup["order"]["status"] == "booked" and not lookup["absence_final"]
        assert client.post("/orders", json=order).json() == lookup["order"]
    with TestClient(create_app(Database(postgres_url)), backend_options=options) as restarted:
        assert (
            restarted.get("/orders", params={"client_ref": str(hold.client_ref)}).json() == lookup
        )
        assert (
            restarted.post(
                "/orders", json=order, headers={"X-Mock-Fault": "rate_limit"}
            ).status_code
            == 403
        )
        assert restarted.post("/orders", json=order).json() == lookup["order"]


def test_real_http_lost_response_and_timed_out_pending_order(
    postgres_url: URL,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R10/R11：真实HTTP丢响应；一次查无不能排除仍在执行的迟到订单。"""
    request = TravelRequest.model_validate(
        {
            "city": "京都",
            "start_date": "2026-11-03",
            "end_date": "2026-11-05",
            "adults": 2,
            "child_ages": [],
            "rooms": 1,
        }
    )
    offer = quote(load_rates()[0][0], request, datetime.now(UTC))
    assert offer is not None
    with serve_http(create_app(Database(postgres_url), faults_enabled=True)) as url:
        with httpx.Client(base_url=url, timeout=2, trust_env=False) as client:
            held = client.post(
                "/holds", json=HoldInput(client_ref=uuid4(), offer=offer).model_dump(mode="json")
            )
            hold = SupplierHold.model_validate(held.json())
            body = OrderInput(client_ref=hold.client_ref, hold_id=hold.hold_id).model_dump(
                mode="json"
            )
            with pytest.raises(httpx.RemoteProtocolError):
                client.post("/orders", json=body, headers={"X-Mock-Fault": "lose_response"})
            lookup = client.get("/orders", params={"client_ref": str(hold.client_ref)}).json()
            assert lookup["order"]["status"] == "booked"
            assert client.post("/orders", json=body).json() == lookup["order"]

            entered, release = threading.Event(), threading.Event()
            original = SupplierService.order

            async def pending(service: SupplierService, body: OrderInput) -> SupplierOrder:
                entered.set()
                if not await asyncio.to_thread(release.wait, 3):
                    raise RuntimeError("测试下单等待未释放")
                return await original(service, body)

            monkeypatch.setattr(SupplierService, "order", pending)
            hold = SupplierHold.model_validate(
                client.post(
                    "/holds",
                    json=HoldInput(client_ref=uuid4(), offer=offer).model_dump(mode="json"),
                ).json()
            )
            body = OrderInput(client_ref=hold.client_ref, hold_id=hold.hold_id).model_dump(
                mode="json"
            )
            try:
                with pytest.raises(httpx.ReadTimeout):
                    client.post("/orders", json=body, timeout=0.05)
                assert entered.is_set()
                lookup = client.get("/orders", params={"client_ref": str(hold.client_ref)}).json()
                assert lookup == {"order": None, "absence_final": False}
            finally:
                release.set()
            # 第二次同键请求与迟到请求由PG串行裁决，不生成两单。
            order = client.post("/orders", json=body).json()
            assert (
                client.get("/orders", params={"client_ref": str(hold.client_ref)}).json()["order"]
                == order
            )
