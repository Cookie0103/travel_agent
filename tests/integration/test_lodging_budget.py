"""住宿两值落库、旧模型兼容、回答只改一个字段及酒店/确认前置真实PG回归。"""

import asyncio
from decimal import Decimal

import pytest

from backend.domain.execution import RunContext
from backend.domain.travel_request import RequestPatch, lodging_budget_relation
from backend.persistence.models import TravelRequestRow
from backend.services.common import ServiceError, transaction
from backend.services.hotels import HotelService
from backend.services.travel import TravelService
from tests.fixtures.legacy_travel_request_v1 import TravelRequest as LegacyRequest
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


def budget(lower: str = "30000", upper: str = "30000", currency: str = "JPY") -> dict[str, object]:
    return {
        "amount": {"lower": lower, "upper": upper},
        "basis": "per_room_night",
        "currency": currency,
    }


def test_both_conflicting_values_save_and_answer_changes_only_trip_budget(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        patch = RequestPatch.model_validate(
            {"expected_revision": 1, "set": {"budget": "50000", "lodging_budget": budget()}}
        )
        saved = await travel.patch_request(context, patch)
        assert saved.request.budget == Decimal("50000")
        assert saved.request.lodging_budget is not None
        assert lodging_budget_relation(saved.request).status == "conflict"
        async with transaction(travel.database) as db:
            row = await db.get(TravelRequestRow, context.session_id)
            assert row is not None
            assert LegacyRequest.model_validate(
                {**row.conditions, "revision": row.revision}
            ).budget == Decimal("50000")
            details = row.request_details
            assert details is not None
            lodging = details["lodging_budget"]
            assert isinstance(lodging, dict)
            amount = lodging["amount"]
            assert isinstance(amount, dict) and amount["lower"] == "30000"
            assert "budget_relation" not in details
        replay = await travel.patch_request(context, patch)
        assert replay.request == saved.request
        changed = await travel.patch_request(
            context,
            RequestPatch.model_validate({"expected_revision": 2, "set": {"budget": "70000"}}),
        )
        assert changed.changed_fields == ("budget",) and changed.request.revision == 3
        assert changed.request.lodging_budget == saved.request.lodging_budget
        assert lodging_budget_relation(await travel.get_request(context)).status == "within"
        noop = await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {"expected_revision": 3, "set": {"lodging_budget": budget("30000.00", "30000.00")}}
            ),
        )
        assert not noop.changed_fields and noop.request.revision == 3

    runner.run(exercise())


def test_old_rows_default_unknown_and_quote_snapshot_stays_legacy_readable(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        assert (await travel.get_request(context)).lodging_budget is None
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {"budget": "50000", "lodging_budget": budget("20000", "25000")},
                }
            ),
        )
        records = await HotelService(travel).search(context, 2, limit=1)
        assert len(records) == 2
        hotel_ids = set()
        for record in records:
            value = record.value
            assert isinstance(value, dict)
            hotel_ids.add(value["hotel_id"])
            assert LegacyRequest.model_validate(value["request"]).revision == 2
        assert len(hotel_ids) == 1
        async with transaction(travel.database) as db:
            row = await db.get(TravelRequestRow, context.session_id)
            assert row
            # 模拟旧写入者仅更新旧conditions/revision，新列内容应保留。
            row.conditions = {**row.conditions, "budget": "60000"}
            row.revision = 3
        current = await travel.get_request(context)
        assert current.budget == Decimal("60000") and current.lodging_budget is not None

    runner.run(exercise())


def test_conflict_blocks_search_and_direct_presentation_before_comparing(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        hotels = HotelService(travel)
        existing = await hotels.search(context, 1, limit=1)
        saved = await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {"expected_revision": 1, "set": {"budget": "50000", "lodging_budget": budget()}}
            ),
        )
        for call in (
            lambda: hotels.search(context, saved.request.revision),
            lambda: hotels.present(context, saved.request.revision, (existing[0].evidence_id,)),
        ):
            with pytest.raises(ServiceError) as error:
                await call()
            assert error.value.code == "conflict" and "以哪个预算为准" in str(error.value)
        # 原报价仍有效；只改预算不会刷新入住Evidence。
        assert await travel.resolve_evidence(context, (existing[0].evidence_id,))

    runner.run(exercise())


def test_budget_conflict_draft_cannot_be_confirmed(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    from backend.services.plans import PlanService
    from tests.integration.test_plans import initial_draft, version_count

    runner, travel, context = travel_setup

    async def exercise() -> None:
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {"expected_revision": 1, "set": {"budget": "50000", "lodging_budget": budget()}}
            ),
        )
        draft = await initial_draft(travel, context)
        assert draft.validation.status == "conflict"
        assert any(check.code == "lodging_budget_conflict" for check in draft.validation.checks)
        with pytest.raises(ServiceError) as failed:
            await PlanService(travel).confirm(context.user_id, draft.draft_id)
        assert failed.value.code == "conflict"
        assert await version_count(travel, draft.plan_id) == 0

    runner.run(exercise())


def test_api_reads_computed_relation_and_never_accepts_stored_relation_flag(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    import httpx

    from backend.api.app import create_app
    from backend.services.sessions import DemoLogin, SessionService

    runner, travel, _ = travel_setup

    async def exercise() -> None:
        sessions = SessionService(travel.database.engine.url, demo_enabled=True)
        try:
            identity = await sessions.create_demo_user(DemoLogin())
            session = await sessions.new_session(identity.user_id)
            headers = {"Authorization": "Bearer " + identity.token}
            path = f"/sessions/{session.session_id}/request"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(create_app(sessions)), base_url="http://local"
            ) as client:
                assert (await client.get(path)).status_code == 401
                first = await client.patch(
                    path,
                    headers=headers,
                    json={
                        "expected_revision": 0,
                        "set": {
                            "budget": "50000",
                            "rooms": 1,
                            "hard_constraints": ["住宿：无要求", "房型：无要求", "床型：无要求"],
                            "start_date": "2026-11-03",
                            "end_date": "2026-11-05",
                            "lodging_budget": budget(),
                        },
                    },
                )
                assert first.status_code == 200
                assert first.json()["request"]["budget_relation"]["status"] == "conflict"
                assert (await client.get(path, headers=headers)).json() == first.json()["request"]
                rejected = await client.patch(
                    path,
                    headers=headers,
                    json={"expected_revision": 1, "set": {"budget_relation": {"status": "within"}}},
                )
                assert rejected.status_code == 422
                changed = await client.patch(
                    path, headers=headers, json={"expected_revision": 1, "set": {"budget": "70000"}}
                )
                assert changed.status_code == 200
                assert changed.json()["changed_fields"] == ["budget"]
                assert changed.json()["request"]["budget_relation"]["status"] == "within"
        finally:
            await sessions.close()

    runner.run(exercise())


def test_rollback_and_reupgrade_keep_lodging_facts(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    from backend.persistence.database import ROOT

    runner, travel, context = travel_setup
    saved = runner.run(
        travel.patch_request(
            context,
            RequestPatch.model_validate(
                {"expected_revision": 1, "set": {"lodging_budget": budget()}}
            ),
        )
    )
    target = travel.database.engine.url
    assert (
        target.host in {"127.0.0.1", "localhost"}
        and target.database is not None
        and target.database.startswith("travel_agent_test_")
    )
    engine = create_engine(target, hide_parameters=True)
    try:
        with engine.begin() as connection:
            config = Config(str(ROOT / "backend/persistence/alembic.ini"))
            config.attributes["connection"] = connection
            command.downgrade(config, "0012")
            command.upgrade(config, "head")
            command.check(config)
    finally:
        engine.dispose()
    current = runner.run(travel.get_request(context))
    assert current == saved.request


def test_budget_update_during_quote_read_cannot_return_stale_comparison(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import UUID

    from backend.domain.evidence import EvidenceRecord

    runner, travel, context = travel_setup

    async def exercise() -> None:
        hotels = HotelService(travel)
        existing = await hotels.search(context, 1, limit=1)
        read = hotels.known_quotes

        async def change_after_read(
            ctx: RunContext, ids: tuple[UUID, ...]
        ) -> tuple[EvidenceRecord, ...]:
            records = await read(ctx, ids)
            await travel.patch_request(
                ctx,
                RequestPatch.model_validate(
                    {"expected_revision": 1, "set": {"budget": "50000", "lodging_budget": budget()}}
                ),
            )
            return records

        monkeypatch.setattr(hotels, "known_quotes", change_after_read)
        with pytest.raises(ServiceError) as failed:
            await hotels.present(context, 1, (existing[0].evidence_id,))
        assert failed.value.code == "conflict"
        assert lodging_budget_relation(await travel.get_request(context)).status == "conflict"

    runner.run(exercise())
