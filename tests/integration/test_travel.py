"""R04/R05：真实PostgreSQL锁、条件更新与Evidence隔离/失效/回滚。"""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import URL, select

from backend.domain.evidence import EvidenceKind, EvidenceRecord, evidence_conditions
from backend.domain.execution import RunContext
from backend.domain.travel_request import (
    RequestPatch,
    TravelRequest,
    apply_request_patch,
    invalidated_kinds,
)
from backend.persistence import travel as repository
from backend.persistence.models import EvidenceRow, TravelRequestRow
from backend.services.common import ServiceError, transaction
from backend.services.sessions import DemoLogin, SessionService
from backend.services.travel import TravelService

pytestmark = pytest.mark.integration


def test_multi_city_sidecar_round_trip_and_segment_only_invalidation(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    """R04/R05：真实PG保留旧conditions，城市段仅存在侧列并原子失效证据。"""
    runner, service, context = travel_setup

    async def exercise() -> None:
        request = await service.get_request(context)
        records = [evidence(request, kind) for kind in ("hotel_offer", "route", "place")]
        await service.record_evidence(context, records)
        segments = [
            {"city": "京都", "arrive": "2026-11-03", "depart": "2026-11-04"},
            {"city": "大阪", "arrive": "2026-11-04", "depart": "2026-11-05"},
        ]
        result = await service.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {"segments": segments, "lodging_budget_unlimited": True},
                }
            ),
        )
        restored = await service.get_request(context)
        assert restored == result.request and restored.revision == 2
        assert restored.model_dump(mode="json")["segments"] == segments
        assert restored.lodging_budget_unlimited
        original_view = await service.get_request_view(context)
        for field in ("city", "start_date", "end_date"):
            with pytest.raises(ValidationError):
                await service.patch_request(
                    context,
                    RequestPatch.model_validate(
                        {"expected_revision": 2, "set": {"segments": segments}, "clear": [field]}
                    ),
                )
        assert await service.get_request_view(context) == original_view
        same = await service.patch_request(
            context,
            RequestPatch.model_validate({"expected_revision": 2, "set": {"segments": segments}}),
        )
        assert same.request == restored and not same.changed_fields
        with pytest.raises(ServiceError) as invalid:
            await service.patch_request(
                context,
                RequestPatch.model_validate({"expected_revision": 2, "set": {"city": "大阪"}}),
            )
        assert invalid.value.reason == "request_merge_invalid"
        assert await service.get_request(context) == restored
        async with transaction(service.database) as db:
            row = await db.get(TravelRequestRow, context.session_id)
            assert row is not None and row.request_details is not None
            assert row.request_details["segments"] == segments
            assert row.request_details["lodging_budget_unlimited"] is True
            assert "segments" not in row.conditions
            assert "lodging_budget_unlimited" not in row.conditions
            rows = await repository.find_evidence(db, context, [r.evidence_id for r in records])
            assert {r.kind: r.invalidated for r in rows} == {
                "hotel_offer": True,
                "route": True,
                "place": False,
            }
        await service.patch_request(context, RequestPatch(expected_revision=2, clear=("segments",)))
        cleared = await service.get_request(context)
        assert cleared.segments is None and cleared.revision == 3
        assert cleared.lodging_budget_unlimited
        limited = await service.patch_request(
            context,
            RequestPatch.model_validate(
                {"expected_revision": 3, "set": {"lodging_budget_unlimited": False}}
            ),
        )
        assert limited.request.revision == 4 and not limited.request.lodging_budget_unlimited
        assert await service.get_request(context) == limited.request

    runner.run(exercise())


def test_segment_derivation_cannot_bypass_manual_city_source(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    """R04：模糊城市段不能通过派生绕过手填优先，明确改段只加一次revision。"""
    runner, service, context = travel_setup

    async def exercise() -> None:
        current = await service.get_request(context)
        patch = RequestPatch.model_validate(
            {
                "expected_revision": 1,
                "set": {
                    "segments": [
                        {"city": "大阪", "arrive": "2026-11-03", "depart": "2026-11-04"},
                        {"city": "京都", "arrive": "2026-11-04", "depart": "2026-11-05"},
                    ]
                },
            }
        )
        skipped = await service.patch_request(context, patch, source="conversation")
        assert skipped.request == current and skipped.skipped_fields == ("segments",)
        explicit = await service.patch_request(
            context, patch, source="conversation", explicit_fields=("segments",)
        )
        assert explicit.request.city == "大阪" and explicit.request.revision == 2
        assert (
            explicit.field_sources["city"] == explicit.field_sources["segments"] == "conversation"
        )
        assert await service.get_request(context) == explicit.request

    runner.run(exercise())


@pytest.fixture
def travel_setup(postgres_url: URL) -> Iterator[tuple[asyncio.Runner, TravelService, RunContext]]:
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        sessions = SessionService(postgres_url, demo_enabled=True)
        identity = runner.run(sessions.create_demo_user(DemoLogin()))
        session = runner.run(sessions.new_session(identity.user_id))
        context = RunContext(identity.user_id, session.session_id)
        service = TravelService(sessions.database)
        try:
            runner.run(
                service.patch_request(
                    context,
                    RequestPatch.model_validate(
                        {
                            "expected_revision": 0,
                            "set": {
                                "city": "京都",
                                "adults": 2,
                                "child_ages": [],
                                "rooms": 1,
                                "hard_constraints": [
                                    "住宿：无要求",
                                    "房型：无要求",
                                    "床型：无要求",
                                ],
                                "start_date": "2026-11-03",
                                "end_date": "2026-11-05",
                            },
                        }
                    ),
                )
            )
            yield runner, service, context
        finally:
            runner.run(sessions.close())


def evidence(request: TravelRequest, kind: EvidenceKind = "hotel_offer") -> EvidenceRecord:
    now = datetime.now(UTC)
    return EvidenceRecord(
        entity_id="fixture:test",
        field_path="total",
        value="5000",
        kind=kind,
        request_revision=request.revision,
        conditions=evidence_conditions(request, kind),
        provider="test-fixture",
        source_ref="fixture:test",
        content_version="v1",
        retrieved_at=now,
        valid_until=now + timedelta(minutes=5),
        data_mode="fixture",
    )


def test_concurrent_updates_only_one_wins(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    """R04：同expected_revision的竞争不能静默覆盖。"""
    runner, service, context = travel_setup

    async def exercise() -> None:
        results = await asyncio.gather(
            *(
                service.patch_request(
                    context,
                    RequestPatch.model_validate(
                        {"expected_revision": 1, "set": {"adults": adults}}
                    ),
                )
                for adults in (3, 4)
            ),
            return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, ServiceError)]
        assert len(errors) == 1 and errors[0].code == "conflict"
        current = await service.get_request(context)
        assert current.revision == 2 and current.adults in {3, 4}

    runner.run(exercise())


def test_changed_dates_invalidate_offers_and_routes_atomically(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    """R04/R05：版本增加与按种类失效在同一事务；旧revision不得补卡。"""
    runner, service, context = travel_setup

    async def exercise() -> None:
        request = await service.get_request(context)
        records = [evidence(request, kind) for kind in ("hotel_offer", "route", "place")]
        await service.record_evidence(context, records)
        await service.patch_request(
            context,
            RequestPatch.model_validate(
                {"expected_revision": 1, "set": {"start_date": "2026-11-04"}}
            ),
        )
        async with transaction(service.database) as db:
            rows = await repository.find_evidence(db, context, [r.evidence_id for r in records])
            flags = {row.kind: row.invalidated for row in rows}
        assert flags == {"hotel_offer": True, "route": True, "place": False}
        for record in records[:2]:
            with pytest.raises(ServiceError) as error:
                await service.resolve_evidence(context, [record.evidence_id])
            assert error.value.code == "conflict"
        # 地点事实只随城市适用，日期变化后仍可解析（产品决策：不随revision失效）。
        assert await service.resolve_evidence(context, [records[2].evidence_id]) == (records[2],)

    runner.run(exercise())


def test_failure_after_invalidation_rolls_back_request_and_evidence(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    """R04：在真实写入后注入异常，不能留下新条件搭配旧证据的半状态。"""
    runner, service, context = travel_setup

    async def exercise() -> None:
        current = await service.get_request(context)
        record = evidence(current)
        await service.record_evidence(context, [record])
        patch = RequestPatch.model_validate({"expected_revision": 1, "set": {"adults": 3}})
        with pytest.raises(RuntimeError, match="injected"):
            async with transaction(service.database) as db:
                row = await repository.owned_request(db, context)
                assert row is not None
                updated, changed = apply_request_patch(current, patch)
                await repository.update_request(
                    db, row, updated, invalidated_kinds(changed), context.run_id
                )
                await db.flush()
                raise RuntimeError("injected after SQL writes")
        assert await service.get_request(context) == current
        assert await service.resolve_evidence(context, [record.evidence_id]) == (record,)

    runner.run(exercise())


def test_forged_expired_foreign_or_wrong_scope_evidence_is_rejected(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    """R05：校验全部引用，不能悄悄丢掉伪造ID或使用其他用户/条件的事实。"""
    runner, service, context = travel_setup

    async def exercise() -> None:
        current = await service.get_request(context)
        record = evidence(current)
        await service.record_evidence(context, [record])
        for foreign in (
            RunContext(uuid4(), context.session_id),
            RunContext(context.user_id, uuid4()),
        ):
            with pytest.raises(ServiceError) as error:
                await service.resolve_evidence(foreign, [record.evidence_id])
            assert error.value.code == "blocked"
        with pytest.raises(ServiceError):
            await service.resolve_evidence(context, [record.evidence_id, uuid4()])
        wrong = evidence(current.model_copy(update={"adults": 5}))
        with pytest.raises(ServiceError) as error:
            await service.record_evidence(context, [wrong])
        assert error.value.code == "conflict"
        async with transaction(service.database) as db:
            row = await db.get(EvidenceRow, record.evidence_id)
            assert row is not None
            expired = record.model_copy(
                update={
                    "retrieved_at": datetime.now(UTC) - timedelta(minutes=10),
                    "valid_until": datetime.now(UTC) - timedelta(minutes=1),
                }
            )
            row.payload = expired.model_dump(mode="json")
        with pytest.raises(ServiceError) as error:
            await service.resolve_evidence(context, [record.evidence_id])
        assert error.value.code == "conflict"

    runner.run(exercise())


def test_noop_does_not_change_revision_or_source_turn(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, service, context = travel_setup

    async def exercise() -> None:
        result = await service.patch_request(
            RunContext(context.user_id, context.session_id), RequestPatch(expected_revision=1)
        )
        assert result.request.revision == 1 and not result.changed_fields
        async with transaction(service.database) as db:
            source = await db.scalar(
                select(TravelRequestRow.source_turn_id).where(
                    TravelRequestRow.session_id == context.session_id
                )
            )
        assert source == context.run_id

    runner.run(exercise())
