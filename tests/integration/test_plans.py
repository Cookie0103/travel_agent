"""R07/R08：真实PostgreSQL草稿、局部改程、锁定、确认竞争与整笔失败回滚。"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select

from backend.agent.demo import COMMANDS, demo_command
from backend.api.app import create_app
from backend.domain.catalog import Place
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution import RunContext
from backend.domain.itinerary import ItineraryProposal, ProposedItem, RouteInput
from backend.domain.plans import PlanDraft, SavedPlan, StageInput
from backend.domain.travel_request import RequestPatch
from backend.persistence import operations, plans
from backend.persistence.models import EvidenceRow, PlanDraftRow, PlanRow, PlanVersionRow
from backend.services.catalog import CatalogService
from backend.services.common import ServiceError, transaction
from backend.services.planning import PlanningService
from backend.services.plans import LockInput, PlanService
from backend.services.sessions import DemoLogin, SessionService
from backend.services.travel import TravelService
from backend.tools.travel import DEFINITIONS, TravelToolExecutor
from tests.integration.test_planning import destinations, proposal
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


def test_fixed_three_day_demo_never_repeats_sightseeing_entities(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    """R06/R08：固定演示也遵守新的实体去重，不用例外绕过业务校验。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await destinations(travel, context)  # 导入公开快照；不调用供应商或模型。
        await travel.patch_request(
            context,
            RequestPatch.model_validate(
                {
                    "expected_revision": 1,
                    "set": {
                        "transport": "walk",
                        "hard_constraints": ["住宿：无要求", "房型：无要求", "床型：无要求"],
                    },
                }
            ),
        )
        outcome = await demo_command(
            TravelToolExecutor(travel), context, COMMANDS[1], lambda _: None, asyncio.Event()
        )
        assert outcome.code is None
        async with transaction(travel.database) as db:
            row = await plans.latest_draft(db, context)
            assert row is not None
            draft = PlanDraft.model_validate(row.payload)
        assert len(draft.content.items) == 6 and draft.validation.status == "partial"
        evidence = await travel.resolve_evidence(
            context, tuple(item.place_evidence_id for item in draft.content.items)
        )
        assert len({record.entity_id for record in evidence}) == 6
        saved = await PlanService(travel).confirm(context.user_id, draft.draft_id)
        assert saved.version == 1

    runner.run(exercise())


async def initial_draft(
    travel: TravelService, context: RunContext, *, closed: bool = False
) -> PlanDraft:
    first, _ = await destinations(travel, context)
    available = await CatalogService(travel).get(context, "places", "osm:way/98115917")
    second = available.evidence[0]  # 金阁寺周三开放；漫画博物馆周三闭馆。
    candidate = proposal(first, closed=closed)
    second_day = candidate.items[0].model_copy(
        update={
            "place_evidence_id": second.evidence_id,
            "start": datetime.fromisoformat("2026-11-04T14:00+09:00"),
            "end": datetime.fromisoformat("2026-11-04T15:00+09:00"),
        }
    )
    candidate = candidate.model_copy(update={"items": (*candidate.items, second_day)})
    return await PlanService(travel).stage(
        context,
        StageInput.model_validate(
            {"change": {"kind": "initial", "proposal": candidate.model_dump(mode="json")}}
        ),
    )


def test_repeated_sightseeing_cannot_stage_or_confirm_a_legacy_draft(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    """R06/R08：重复的旧提醒草稿也必须在确认时重新校验；拒绝不能生成正式版本。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        service = PlanService(travel)
        valid = await initial_draft(travel, context)
        first, second = valid.content.items
        duplicate_content = valid.content.model_copy(
            update={
                "items": (
                    first,
                    second.model_copy(update={"place_evidence_id": first.place_evidence_id}),
                )
            }
        )
        candidate = duplicate_content.proposal(valid.request_revision)
        duplicate_args = StageInput.model_validate(
            {"change": {"kind": "initial", "proposal": candidate.model_dump(mode="json")}}
        )
        feedback = await PlanningService(travel).validate(context, candidate)
        assert feedback.status == "conflict"
        assert any(c.code == "repeated_place_warning" for c in feedback.checks)
        with pytest.raises(ServiceError, match="重复景点"):
            await service.stage(
                context,
                duplicate_args,
            )
        async with transaction(travel.database) as db:
            row = await db.get(PlanDraftRow, valid.draft_id)
            assert row is not None
            # 模拟升级前已暂存的重复草稿，保留旧 partial 报告，确认必须现算。
            row.payload = valid.model_copy(update={"content": duplicate_content}).model_dump(
                mode="json"
            )
            operations.save(
                db, context.session_id, "stage_plan", operations.key(duplicate_args), row.payload
            )
            drafts = await db.scalar(
                select(func.count())
                .select_from(PlanDraftRow)
                .where(PlanDraftRow.plan_id == valid.plan_id)
            )
            assert drafts == 1
        with pytest.raises(ServiceError, match="重复景点"):
            await service.stage(context, duplicate_args)  # 旧 operation 幂等回放也必须现算。
        with pytest.raises(ServiceError, match="硬冲突"):
            await service.confirm(context.user_id, valid.draft_id)
        assert await version_count(travel, valid.plan_id) == 0
        async with transaction(travel.database) as db:
            row = await db.get(PlanDraftRow, valid.draft_id)
            assert row is not None and row.confirmed_version is None
        # 同一会话允许提交修复候选；阻止重复不等于让整个旅行永久失败。
        fixed_proposal = valid.content.proposal(valid.request_revision)
        fixed_proposal = fixed_proposal.model_copy(
            update={
                "items": (
                    fixed_proposal.items[0].model_copy(update={"note": "修复后的不同景点行程"}),
                    fixed_proposal.items[1],
                )
            }
        )
        fixed = await service.stage(
            context,
            StageInput.model_validate(
                {
                    "change": {
                        "kind": "initial",
                        "proposal": fixed_proposal.model_dump(mode="json"),
                    }
                }
            ),
        )
        assert fixed.validation.status == "partial"
        saved = await service.confirm(context.user_id, fixed.draft_id)
        assert saved.version == 1 and await version_count(travel, valid.plan_id) == 1

    runner.run(exercise())


def patch_stage(saved: SavedPlan) -> StageInput:
    second = saved.content.items[1]
    replacement = second.proposed().model_dump(mode="json") | {
        "start": "2026-11-04T15:00+09:00",
        "end": "2026-11-04T16:00+09:00",
    }
    return StageInput.model_validate(
        {
            "change": {
                "kind": "patch",
                "plan_id": str(saved.plan_id),
                "patch": {
                    "base_version": saved.version,
                    "expected_revision": saved.request_revision,
                    "operations": [
                        {"op": "update", "item_id": str(second.item_id), "item": replacement}
                    ],
                },
            }
        }
    )


async def version_count(travel: TravelService, plan_id: UUID) -> int:
    async with transaction(travel.database) as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(PlanVersionRow)
                .where(PlanVersionRow.plan_id == plan_id)
            )
            or 0
        )


def test_stage_does_not_save_and_parallel_confirm_returns_one_immutable_version(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    service = PlanService(travel)

    async def exercise() -> None:
        draft = await initial_draft(travel, context)
        assert (
            draft.validation.status == "partial" and await version_count(travel, draft.plan_id) == 0
        )
        with pytest.raises(ServiceError, match="尚无"):
            await service.get(context.user_id, draft.plan_id)
        first, repeated = await asyncio.gather(
            service.confirm(context.user_id, draft.draft_id),
            service.confirm(context.user_id, draft.draft_id),
        )
        assert (
            first == repeated
            and first.version == 1
            and await version_count(travel, draft.plan_id) == 1
        )
        second_draft = await service.stage(context, patch_stage(first))
        second = await service.confirm(context.user_id, second_draft.draft_id)
        assert second.version == 2 and second.content.items[0] == first.content.items[0]
        assert second.content.items[1].item_id == first.content.items[1].item_id
        replay = await service.confirm(context.user_id, draft.draft_id)
        summary = await travel.business_context(context)
        assert summary["saved_plan"] == {"plan_id": str(first.plan_id), "version": 2}
        assert (
            replay == first
            and replay.version == 1
            and await version_count(travel, draft.plan_id) == 2
        )
        with pytest.raises(ServiceError, match="版本已变化"):
            await service.stage(context, patch_stage(first))

    runner.run(exercise())


@pytest.mark.parametrize(
    "fault", ["expired", "revision", "evidence", "hard_conflict", "other_user"]
)
def test_invalid_confirmation_leaves_version_and_confirmation_marker_unchanged(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], fault: str
) -> None:
    runner, travel, context = travel_setup
    service = PlanService(travel)

    async def exercise() -> None:
        draft = await initial_draft(travel, context, closed=fault == "hard_conflict")
        user = context.user_id
        if fault == "expired":
            async with transaction(travel.database) as db:
                row = await db.get(PlanDraftRow, draft.draft_id)
                assert row is not None
                row.payload = draft.model_copy(
                    update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
                ).model_dump(mode="json")
        elif fault == "revision":
            await travel.patch_request(
                context,
                RequestPatch.model_validate({"expected_revision": 1, "set": {"budget": "10000"}}),
            )
        elif fault == "evidence":
            async with transaction(travel.database) as db:
                evidence_row = await db.get(EvidenceRow, draft.content.items[0].place_evidence_id)
                assert evidence_row is not None
                evidence_row.payload = evidence_row.payload | {
                    "retrieved_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
                    "valid_until": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                }
        elif fault == "other_user":
            user = uuid4()
        with pytest.raises(ServiceError) as failed:
            await service.confirm(user, draft.draft_id)
        assert failed.value.code in {"conflict", "blocked"}
        assert await version_count(travel, draft.plan_id) == 0
        async with transaction(travel.database) as db:
            parent = await db.get(PlanRow, draft.plan_id)
            row = await db.get(PlanDraftRow, draft.draft_id)
            assert parent is not None and parent.current_version == 0
            assert row is not None and row.confirmed_version is None

    runner.run(exercise())


def test_competing_drafts_lock_versions_and_user_owned_locks(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup
    service = PlanService(travel)

    async def exercise() -> None:
        first, competing = (
            await initial_draft(travel, context),
            await initial_draft(travel, context),
        )
        saved = await service.confirm(context.user_id, first.draft_id)
        with pytest.raises(ServiceError, match="正式版本"):
            await service.confirm(context.user_id, competing.draft_id)
        assert (await service.get_draft(context.user_id, competing.draft_id))[
            "version_changed"
        ] is True
        with pytest.raises(ServiceError, match="旧正式版本"):
            await service.get_draft(
                context.user_id, competing.draft_id, session_id=context.session_id
            )
        locked = await service.locks(
            context.user_id,
            saved.plan_id,
            LockInput(expected_version=1, locked_item_ids=(saved.content.items[1].item_id,)),
        )
        assert locked.version == 2 and locked.content.items[1].locked
        with pytest.raises(ServiceError, match="锁定"):
            await service.stage(context, patch_stage(locked))
        with pytest.raises(ServiceError):
            await service.locks(
                context.user_id,
                saved.plan_id,
                LockInput(expected_version=2, locked_item_ids=(uuid4(),)),
            )
        with pytest.raises(ServiceError, match="不存在"):
            await service.get(uuid4(), saved.plan_id)
        with pytest.raises(ServiceError, match="不存在"):
            await service.get_draft(uuid4(), first.draft_id)
        await travel.patch_request(
            context, RequestPatch.model_validate({"expected_revision": 1, "set": {"rooms": 2}})
        )
        view = await service.get(context.user_id, saved.plan_id)
        # 人数/房间变化不影响仅含地点事实的计划（地点证据只随城市适用）。
        assert view["needs_refresh"] == [] and view["historical"] is True
        await travel.patch_request(
            context, RequestPatch.model_validate({"expected_revision": 2, "set": {"city": "大阪"}})
        )
        view = await service.get(context.user_id, saved.plan_id)
        assert view["needs_refresh"] and view["historical"] is True
        assert await service.confirm(context.user_id, first.draft_id) == saved

    runner.run(exercise())


def test_four_validations_allow_staging_same_final_candidate_but_not_new_repair(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        first, _ = await destinations(travel, context)
        executor = TravelToolExecutor(travel)
        candidate = proposal(first)
        for _ in range(4):
            result = await executor.execute(
                context, "validate_itinerary", candidate.model_dump(mode="json")
            )
            assert result.code is None
        args: dict[str, object] = {
            "change": {"kind": "initial", "proposal": candidate.model_dump(mode="json")}
        }
        result = await executor.execute(context, "stage_plan_change", args)
        assert result.code is None and executor.validations == 4
        draft_id = UUID(str(result.data["draft_id"]))
        mixed = await executor.execute(
            context,
            "present_travel_result",
            {"component": "itinerary", "draft_id": str(draft_id), "expected_revision": 1},
        )
        assert mixed.code == "validation"
        assert mixed.data == {}
        assert "两类参数不得混填" in mixed.suggestion
        presented = await executor.execute(
            context, "present_travel_result", {"component": "itinerary", "draft_id": str(draft_id)}
        )
        assert presented.code is None and presented.data["cards"]
        assert await version_count(travel, UUID(str(result.data["plan_id"]))) == 0
        assert "confirm_plan" not in {d.name for d in DEFINITIONS}
        changed = candidate.model_copy(
            update={
                "items": (
                    candidate.items[0].model_copy(
                        update={"end": datetime.fromisoformat("2026-11-03T11:30+09:00")}
                    ),
                )
            }
        )
        rejected = await executor.execute(
            context,
            "stage_plan_change",
            {"change": {"kind": "initial", "proposal": changed.model_dump(mode="json")}},
        )
        assert rejected.code == "blocked"

    runner.run(exercise())


def test_confirm_api_requires_identity_and_only_saves_owned_draft(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, _ = travel_setup

    async def exercise() -> None:
        sessions = SessionService(travel.database.engine.url, demo_enabled=True)
        app = create_app(sessions)
        try:
            identity = await sessions.create_demo_user(DemoLogin())
            other = await sessions.create_demo_user(DemoLogin())
            session = await sessions.new_session(identity.user_id)
            draft = await initial_draft(
                TravelService(sessions.database), RunContext(identity.user_id, session.session_id)
            )
            headers = {"Authorization": "Bearer " + identity.token}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://local"
            ) as client:
                path = f"/plan-drafts/{draft.draft_id}/confirm"
                assert (await client.post(path)).status_code == 401
                assert (
                    await client.post(path, headers={"Authorization": "Bearer " + other.token})
                ).status_code == 404
                response = await client.post(path, headers=headers)
                assert response.status_code == 200 and response.json()["version"] == 1
                assert (await client.post(path, headers=headers)).json() == response.json()
                saved = await client.get(f"/plans/{draft.plan_id}", headers=headers)
                assert saved.status_code == 200 and saved.json()["cards"]
                assert (await client.get(f"/plan-drafts/{draft.draft_id}", headers=headers)).json()[
                    "status"
                ] == "confirmed"
        finally:
            await sessions.close()

    runner.run(exercise())


def test_large_partial_draft_still_presents_ids_cards_and_validation(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    """R07审查回归：24项/21路段合法patch不能因展示摘要超过8k而被整体丢弃。"""
    runner, travel, context = travel_setup

    async def exercise() -> None:
        await travel.patch_request(
            context,
            RequestPatch.model_validate({"expected_revision": 1, "set": {"transport": "walk"}}),
        )
        first, _ = await destinations(travel, context)
        slots = [(day, hour) for day in (3, 4, 5) for hour in range(9, 17)]
        place_records = tuple(
            first.model_copy(
                update={
                    "evidence_id": uuid4(),
                    "entity_id": f"fixture:large-place-{i}",
                    "value": Place.model_validate(first.value)
                    .model_copy(update={"place_id": f"fixture:large-place-{i}"})
                    .model_dump(mode="json"),
                    "provider": "test-fixture",
                    "source_ref": "fixture:large-unique-plan",
                    "content_version": "1",
                }
            )
            for i in range(len(slots))
        )
        await travel.record_evidence(context, place_records)
        legs = [
            {
                "from_evidence_id": str(place_records[i - 1].evidence_id),
                "to_evidence_id": str(place_records[i].evidence_id),
                "departure": f"2026-11-{day:02d}T{hour - 1:02d}:30+09:00",
            }
            for i, (day, hour) in enumerate(slots)
            if hour > 9
        ]
        routes: list[EvidenceRecord] = []
        planning = PlanningService(travel)
        for offset in range(0, len(legs), 6):
            routes.extend(
                await planning.routes(
                    context,
                    RouteInput.model_validate(
                        {"expected_revision": 2, "legs": legs[offset : offset + 6]}
                    ),
                )
            )
        route_iter = iter(routes)
        items = tuple(
            ProposedItem(
                place_evidence_id=place_records[i].evidence_id,
                start=datetime.fromisoformat(f"2026-11-{day:02d}T{hour:02d}:00+09:00"),
                end=datetime.fromisoformat(f"2026-11-{day:02d}T{hour:02d}:30+09:00"),
                route_evidence_id=next(route_iter).evidence_id if hour > 9 else None,
            )
            for i, (day, hour) in enumerate(slots)
        )
        candidate = ItineraryProposal(expected_revision=2, items=items)
        service = PlanService(travel)
        initial = await service.stage(
            context,
            StageInput.model_validate(
                {"change": {"kind": "initial", "proposal": candidate.model_dump(mode="json")}}
            ),
        )
        saved = await service.confirm(context.user_id, initial.draft_id)
        operations = [
            {
                "op": "update",
                "item_id": str(item.item_id),
                "item": item.proposed()
                .model_copy(update={"end": item.end - timedelta(minutes=5)})
                .model_dump(mode="json"),
            }
            for item in saved.content.items
        ]
        executor = TravelToolExecutor(travel)
        staged = await executor.execute(
            context,
            "stage_plan_change",
            {
                "change": {
                    "kind": "patch",
                    "plan_id": str(saved.plan_id),
                    "patch": {"base_version": 1, "expected_revision": 2, "operations": operations},
                }
            },
        )
        validation = staged.data["validation"]
        assert (
            staged.code is None
            and isinstance(validation, dict)
            and validation["status"] == "partial"
        )
        presented = await executor.execute(
            context,
            "present_travel_result",
            {"component": "itinerary", "draft_id": staged.data["draft_id"]},
        )
        assert (
            presented.code is None
            and len(json.dumps(presented.payload(), ensure_ascii=False)) <= 8000
        )
        assert presented.data["draft_id"] == staged.data["draft_id"] and presented.data["cards"]
        assert presented.data["cards_count"] == 24 and presented.data["changes_count"] == 24
        assert presented.data["changes_truncated"] is True and presented.data["validation"]

    runner.run(exercise())
