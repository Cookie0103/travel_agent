"""草稿与确认用例；同一会话锁内重新校验证据、条件和版本，重复确认返回原版本。"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.live_data import LiveData
from backend.domain.catalog import Place
from backend.domain.execution import RunContext
from backend.domain.itinerary import PLAN_ITEM_LIMIT, ItineraryProposal, ValidationReport
from backend.domain.plans import (
    InitialStage,
    PlanContent,
    PlanDraft,
    StageInput,
    apply_plan_patch,
    differences,
    initial_content,
)
from backend.domain.plans import (
    SavedPlan as SavedPlan,
)
from backend.domain.travel_request import TravelRequest
from backend.persistence import operations, plans
from backend.persistence import travel as requests
from backend.persistence.models import PlanRow
from backend.services.calendar import calendar
from backend.services.common import ServiceError, transaction
from backend.services.hotels import cards as hotel_cards
from backend.services.planning import validate_proposal
from backend.services.travel import (
    TravelService,
    hydrate_records,
    request_from_row,
    require_revision,
)
from backend.services.views import PlanView


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    plan_id: UUID


class LockInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_version: int = Field(strict=True, ge=1)
    locked_item_ids: tuple[UUID, ...] = Field(max_length=PLAN_ITEM_LIMIT)


def require_unique_sightseeing(report: ValidationReport) -> None:
    """拦住跳过显式校验与幂等回放；修复选择仍交给现有 SDK 工具往返。"""
    if any(c.code == "repeated_place_warning" and c.status == "conflict" for c in report.checks):
        raise ServiceError(
            409,
            "conflict",
            "行程含重复景点，不能暂存；请先validate_itinerary定位，保留一次并用未使用的"
            "有来源景点替换其余项，重新estimate_routes检查相邻路段，再校验和暂存。",
        )


def require_legacy_write(request: TravelRequest, content: PlanContent | None = None) -> None:
    """回退版本只读新格式，防止旧写入逻辑丢字段或放宽旧边界。"""
    if (
        request.segments
        or request.lodging_budget_unlimited
        or (content is not None and (content.hotel_stays or len(content.items) > 24))
    ):
        raise ServiceError(
            409,
            "conflict",
            "当前兼容版本只读取新格式行程，暂不修改或确认。",
            "new_format_read_only",
        )


class PlanService:
    def __init__(self, travel: TravelService) -> None:
        self.travel = travel

    async def calendar(self, user_id: UUID, plan_id: UUID) -> tuple[str, int]:
        view = PlanView.model_validate(await self.get(user_id, plan_id))
        assert view.version is not None
        return calendar(view), view.version

    async def stage(
        self,
        context: RunContext,
        arguments: StageInput,
        *,
        before_validate: Callable[[ItineraryProposal], None] | None = None,
    ) -> PlanDraft:
        async with transaction(self.travel.database) as db:
            request = request_from_row(await requests.owned_request(db, context))
            require_legacy_write(request)
            operation_key = operations.key(arguments)
            cached = await operations.result(db, context.session_id, "stage_plan", operation_key)
            if cached is not None:
                saved = PlanDraft.model_validate(cached)
                require_legacy_write(request, saved.content)
                require_revision(request, saved.request_revision)
                current_plan = await plans.for_session(db, context)
                if current_plan is None or current_plan.current_version != saved.base_version:
                    raise ServiceError(409, "conflict", "正式行程版本已变化，请重新读取")
                if datetime.now(UTC) >= saved.expires_at:
                    raise ServiceError(
                        409, "conflict", "原草稿已过期，请重新查询后生成", "draft_expired"
                    )
                report = await validate_proposal(
                    db, context, request, saved.content.proposal(request.revision), self.travel.live
                )
                require_unique_sightseeing(report)
                return saved.model_copy(update={"validation": report})
            row = await plans.for_session(db, context)
            change = arguments.change
            previous = await plans.version(db, row) if row else None
            if previous is not None:
                require_legacy_write(request, previous.content)
            if isinstance(change, InitialStage):
                require_revision(request, change.proposal.expected_revision)
                if previous is not None:
                    raise ServiceError(
                        409, "conflict", "已有正式行程，请读取后使用局部patch", "plan_exists"
                    )
                content = initial_content(change.proposal)
                if row is None:
                    row = PlanRow(
                        user_id=context.user_id, session_id=context.session_id, current_version=0
                    )
                    db.add(row)
                    await db.flush()
            else:
                require_revision(request, change.patch.expected_revision)
                if row is None or row.id != change.plan_id or previous is None:
                    raise ServiceError(404, "blocked", "正式行程不存在或不属于当前会话")
                if previous.version != change.patch.base_version:
                    raise ServiceError(409, "conflict", "正式行程版本已变化，请重新读取")
                try:
                    content = apply_plan_patch(previous, change.patch)
                except ValueError:
                    raise ServiceError(
                        422, "validation", "patch引用不存在、锁定或无效的行程项", "patch_invalid"
                    ) from None
            # 新模型先上线；按段校验在T2.2接通前，禁止旧服务写坏新内容。
            require_legacy_write(request, content)
            proposal = content.proposal(request.revision)
            if before_validate is not None:
                before_validate(proposal)
            report = await validate_proposal(db, context, request, proposal, self.travel.live)
            require_unique_sightseeing(report)
            draft = PlanDraft(
                plan_id=row.id,
                base_version=row.current_version,
                request_revision=request.revision,
                content=content,
                changes=differences(previous.content if previous else None, content),
                hotel_changed=(previous.content.hotel_evidence_id if previous else None)
                != content.hotel_evidence_id,
                validation=report,
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
            await plans.add_draft(db, context, draft)
            operations.save(
                db, context.session_id, "stage_plan", operation_key, draft.model_dump(mode="json")
            )
            return draft

    async def confirm(self, user_id: UUID, draft_id: UUID) -> SavedPlan:
        async with transaction(self.travel.database) as db:
            draft_row = await plans.draft(db, user_id, draft_id)
            if draft_row is None:
                raise ServiceError(404, "blocked", "草稿不存在")
            context = RunContext(user_id, draft_row.session_id)
            request = request_from_row(await requests.owned_request(db, context))
            # 不变量：先获取会话锁，再刷新确认标记；锁前读取不能判定并发幂等结果。
            await db.refresh(draft_row)
            row = await plans.for_session(db, context)
            if row is None or row.id != draft_row.plan_id:
                raise ServiceError(404, "blocked", "行程不存在")
            if draft_row.confirmed_version is not None:
                saved = await plans.version(db, row, draft_row.confirmed_version)
                if saved is None:
                    raise ServiceError(503, "unavailable", "已确认行程记录缺失")
                return saved
            draft = PlanDraft.model_validate(draft_row.payload)
            require_legacy_write(request, draft.content)
            if datetime.now(UTC) >= draft.expires_at:
                raise ServiceError(409, "conflict", "草稿已过期，请重新生成")
            require_revision(request, draft.request_revision)
            if row.current_version != draft.base_version:
                raise ServiceError(409, "conflict", "正式版本已变化，请重新生成patch")
            report = await validate_proposal(
                db, context, request, draft.content.proposal(request.revision), self.travel.live
            )
            if report.status == "conflict":
                raise ServiceError(409, "conflict", "草稿存在硬冲突，不能保存；请修正后重新确认")
            saved = SavedPlan(
                plan_id=row.id,
                version=row.current_version + 1,
                request_revision=request.revision,
                content=draft.content,
                validation=report,
                saved_at=datetime.now(UTC),
            )
            await plans.save(db, row, saved)
            draft_row.confirmed_version = saved.version
            await db.flush()
            return saved

    async def get(
        self, user_id: UUID, plan_id: UUID, *, session_id: UUID | None = None
    ) -> dict[str, object]:
        async with transaction(self.travel.database) as db:
            row = await plans.owned(db, user_id, plan_id)
            if row is None or (session_id is not None and row.session_id != session_id):
                raise ServiceError(404, "blocked", "行程不存在")
            context = RunContext(user_id, row.session_id)
            request = request_from_row(await requests.owned_request(db, context))
            await db.refresh(row)
            saved = await plans.version(db, row)
            if saved is None:
                raise ServiceError(404, "blocked", "尚无正式保存的行程")
            return await content_view(
                db,
                context,
                request,
                saved.content,
                {
                    **saved.model_dump(mode="json", exclude={"content", "validation"}),
                    "validation": saved.validation.feedback(),
                    "historical": True,
                },
                self.travel.live,
            )

    async def get_draft(
        self, user_id: UUID, draft_id: UUID, *, session_id: UUID | None = None
    ) -> dict[str, object]:
        async with transaction(self.travel.database) as db:
            row = await plans.draft(db, user_id, draft_id)
            if row is None:
                raise ServiceError(404, "blocked", "草稿不存在")
            if session_id is not None and row.session_id != session_id:
                raise ServiceError(404, "blocked", "草稿不属于当前会话")
            draft = PlanDraft.model_validate(row.payload)
            context = RunContext(user_id, row.session_id)
            request = request_from_row(await requests.owned_request(db, context))
            await db.refresh(row)
            report = draft.validation
            parent = await plans.for_session(db, context)
            version_changed = parent is None or parent.current_version != draft.base_version
            if session_id is not None:
                if row.confirmed_version is not None or datetime.now(UTC) >= draft.expires_at:
                    raise ServiceError(
                        409, "conflict", "草稿已确认或过期，请读取正式行程或重新生成"
                    )
                require_revision(request, draft.request_revision)
                if version_changed:
                    raise ServiceError(409, "conflict", "草稿基于旧正式版本，请重新生成patch")
                if not (
                    request.segments
                    or request.lodging_budget_unlimited
                    or draft.content.hotel_stays
                    or len(draft.content.items) > 24
                ):
                    report = await validate_proposal(
                        db,
                        context,
                        request,
                        draft.content.proposal(request.revision),
                        self.travel.live,
                    )
            data = {
                **draft.model_dump(mode="json", exclude={"content", "validation"}),
                "validation": report.feedback(),
                "status": "confirmed" if row.confirmed_version else "staged",
                "expired": datetime.now(UTC) >= draft.expires_at,
                "conditions_changed": request.revision != draft.request_revision,
                "version_changed": version_changed,
            }
            return await content_view(db, context, request, draft.content, data, self.travel.live)

    async def locks(self, user_id: UUID, plan_id: UUID, arguments: LockInput) -> SavedPlan:
        async with transaction(self.travel.database) as db:
            row = await plans.owned(db, user_id, plan_id)
            if row is None:
                raise ServiceError(404, "blocked", "行程不存在")
            request = request_from_row(
                await requests.owned_request(db, RunContext(user_id, row.session_id))
            )
            await db.refresh(row)
            current = await plans.version(db, row)
            if current is None or current.version != arguments.expected_version:
                raise ServiceError(409, "conflict", "正式行程版本已变化")
            require_legacy_write(request, current.content)
            ids = set(arguments.locked_item_ids)
            if len(ids) != len(arguments.locked_item_ids) or ids - {
                item.item_id for item in current.content.items
            }:
                raise ServiceError(
                    422, "validation", "锁定列表包含重复或不存在的item_id", "lock_invalid"
                )
            content = PlanContent(
                items=tuple(
                    item.model_copy(update={"locked": item.item_id in ids})
                    for item in current.content.items
                ),
                hotel_evidence_id=current.content.hotel_evidence_id,
            )
            if content == current.content:
                return current
            saved = current.model_copy(
                update={
                    "version": current.version + 1,
                    "content": content,
                    "saved_at": datetime.now(UTC),
                }
            )
            await plans.save(db, row, saved)
            return saved


async def content_view(
    db: AsyncSession,
    context: RunContext,
    request: TravelRequest,
    content: PlanContent,
    data: dict[str, object],
    live: LiveData | None = None,
) -> dict[str, object]:
    """历史内容可以读取；过期或旧条件引用显式标记，不能伪装成当前事实。"""
    rows = await requests.find_evidence(
        db, context, content.proposal(request.revision).evidence_ids()
    )
    records = await hydrate_records(tuple(requests.evidence_from_row(row) for row in rows), live)
    evidence = {record.evidence_id: record for record in records}
    stale = [
        str(row.id)
        for row in rows
        if row.invalidated or not evidence[row.id].applicable(request, datetime.now(UTC))
    ]
    stale.extend(
        str(id) for id in content.proposal(request.revision).evidence_ids() if id not in evidence
    )
    cards = []
    for item in content.items:
        record = evidence.get(item.place_evidence_id)
        place = Place.model_validate(record.value) if record and record.value is not None else None
        cards.append(
            {
                **item.model_dump(mode="json"),
                "name": place.name if place else "历史地点证据缺失",
                "source_ref": record.source_ref if record else None,
                "data_mode": record.data_mode if record else "snapshot",
            }
        )
    return {
        **data,
        **(
            {"hotel_stays": [stay.model_dump(mode="json") for stay in content.hotel_stays]}
            if content.hotel_stays
            else {}
        ),
        "cards": cards,
        "hotel_evidence_id": str(content.hotel_evidence_id) if content.hotel_evidence_id else None,
        "hotel": hotel_cards((evidence[content.hotel_evidence_id],), request)[0]
        if content.hotel_evidence_id in evidence
        else None,
        "needs_refresh": stale,
        "guidance": "历史校验报告与快照，当前保存/预订仍须重新校验",
    }
