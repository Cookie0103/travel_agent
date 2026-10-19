"""P-R2：所有GET路由在另一连接持有会话行锁时仍能返回，且不顺手创建travel_requests行。"""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import URL, create_engine, text

from backend.api.app import create_app
from backend.domain.choices import TRANSPORT_PACE_GROUPS
from backend.domain.execution import RunContext
from backend.persistence import runs
from backend.services.bookings import BookingService
from backend.services.choices import ChoiceService
from backend.services.common import transaction
from backend.services.plans import PlanService
from backend.services.sessions import SessionService
from backend.services.travel import TravelService
from mock_supplier.service import SupplierService
from tests.integration.test_bookings import select_offer
from tests.integration.test_input_limits import _finishes_while_locked
from tests.integration.test_plans import initial_draft
from tests.integration.test_sessions import login

pytestmark = pytest.mark.integration

REQUEST = {
    "expected_revision": 0,
    "set": {
        "city": "京都",
        "start_date": "2026-11-03",
        "end_date": "2026-11-05",
        "adults": 2,
        "child_ages": [],
        "rooms": 1,
        "hard_constraints": ["住宿：无要求", "房型：无要求", "床型：无要求"],
    },
}


@dataclass
class World:
    client: TestClient
    headers: dict[str, str]
    session_id: UUID
    paths: dict[str, str]


@pytest.fixture
def world(postgres_url: URL, unrepaired: None) -> Iterator[World]:
    sessions = SessionService(postgres_url, demo_enabled=True)
    travel = TravelService(sessions.database)
    bookings = BookingService(travel, SupplierService(sessions.database))
    app = create_app(sessions, booking_service=bookings)
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
        assert client.portal is not None
        portal = client.portal
        headers = login(client)
        sid = client.post("/sessions", headers=headers).json()["session_id"]
        assert (
            client.patch(f"/sessions/{sid}/request", headers=headers, json=REQUEST).status_code
            == 200
        )
        user_id = portal.call(sessions.authenticate, headers["Authorization"])
        context = RunContext(user_id, UUID(sid))

        async def build() -> tuple[UUID, UUID, UUID, UUID, UUID]:
            plans = PlanService(travel)
            draft = await initial_draft(travel, context)
            staged = await initial_draft(travel, context)
            saved = await plans.confirm(user_id, draft.draft_id)
            held = await bookings.hold(context, await select_offer(travel, context))
            async with transaction(travel.database) as db:
                row = await runs.create(
                    db, user_id, context.session_id, uuid4(), "先确认", "offline"
                )
                active = RunContext(user_id, context.session_id, row.id)
            choice = await ChoiceService(travel).create(active, "form", 1, TRANSPORT_PACE_GROUPS)
            return saved.plan_id, staged.draft_id, held.booking_id, choice.choice_id, row.id

        plan_id, draft_id, booking_id, choice_id, run_id = portal.call(build)
        paths = {
            "session": f"/sessions/{sid}",
            "request": f"/sessions/{sid}/request",
            "choice": f"/sessions/{sid}/choices/{choice_id}",
            "runs": f"/sessions/{sid}/runs",
            "run": f"/runs/{run_id}",
            "plan": f"/plans/{plan_id}",
            "calendar": f"/plans/{plan_id}/calendar.ics",
            "draft": f"/plan-drafts/{draft_id}",
            "bookings": f"/sessions/{sid}/bookings",
            "booking": f"/bookings/{booking_id}",
            "sessions": "/sessions",
            "preferences": "/preferences",
            "memory": "/memory",
        }
        yield World(client, headers, UUID(sid), paths)
        portal.call(sessions.close)


@pytest.mark.parametrize(
    "name",
    [
        "session", "request", "choice", "runs", "run", "plan", "calendar",
        "draft", "bookings", "booking", "sessions", "preferences", "memory",
    ],
)  # fmt: skip
def test_get_route_does_not_wait_for_session_lock(
    world: World, postgres_url: URL, name: str
) -> None:
    path = world.paths[name]
    assert world.client.get(path, headers=world.headers).status_code == 200, "无锁时应成功"
    assert _finishes_while_locked(
        postgres_url,
        world.session_id,
        lambda: world.client.get(path, headers=world.headers).status_code == 200,
    ), f"GET {name} 被会话行锁阻塞"


def test_get_on_fresh_session_never_creates_request_row(world: World, postgres_url: URL) -> None:
    fresh = world.client.post("/sessions", headers=world.headers).json()["session_id"]
    for path in (f"/sessions/{fresh}/request", f"/sessions/{fresh}/bookings"):
        assert world.client.get(path, headers=world.headers).status_code == 200, path
    engine = create_engine(postgres_url)
    with engine.connect() as connection:
        rows = connection.execute(
            text("select count(*) from travel_requests where session_id = :s"), {"s": fresh}
        ).scalar()
    engine.dispose()
    assert rows == 0
