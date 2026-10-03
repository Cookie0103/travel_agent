"""旅行工具的固定注册表与执行边界；SDK负责选工具，这里只验证和调用业务服务。"""

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend.domain.booking import HoldHotelInput
from backend.domain.execution import RunContext
from backend.domain.itinerary import ItineraryProposal, RouteInput
from backend.domain.plans import StageInput
from backend.domain.travel_request import RequestPatch
from backend.services.bookings import BookingService
from backend.services.catalog import CatalogResult, CatalogService
from backend.services.common import ServiceError
from backend.services.hotels import HotelService, cards
from backend.services.planning import PlanningService
from backend.services.plans import PlanInput, PlanService
from backend.services.travel import TravelService
from backend.tools.contracts import RESULT_LIMIT, ToolDefinition, ToolResult
from backend.tools.search import DEFINITIONS as SEARCH_DEFINITIONS
from backend.tools.search import ContentSearchInput, PlaceSearchInput


class EntityInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    entity_id: str = Field(
        min_length=1,
        max_length=100,
        description="搜索返回的place_id或article_id；不是evidence_id。证据UUID仅用于行程/路线引用。",
    )


class SkillInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: Literal["hotel-comparison", "itinerary-revision"]


class HotelSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_revision: int = Field(strict=True, ge=0)
    hotel_id: str | None = Field(default=None, min_length=1, max_length=100)
    limit: int = Field(default=4, strict=True, ge=1, le=6)


class RefreshOfferInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_revision: int = Field(strict=True, ge=0)
    offer_id: UUID


class PresentationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    component: Literal["hotel_comparison", "itinerary"]
    expected_revision: int | None = Field(default=None, strict=True, ge=0)
    offer_ids: tuple[UUID, ...] = Field(default=(), max_length=6)
    draft_id: UUID | None = None

    @model_validator(mode="after")
    def valid_component(self) -> "PresentationInput":
        if len(self.offer_ids) != len(set(self.offer_ids)):
            raise ValueError("报价ID不能重复")
        if self.component == "hotel_comparison":
            if self.expected_revision is None or not self.offer_ids or self.draft_id is not None:
                raise ValueError("酒店卡片仅需要版本和1至6个报价ID")
        elif self.draft_id is None or self.offer_ids or self.expected_revision is not None:
            raise ValueError("行程卡片仅需要草稿ID")
        return self


DEFINITIONS = (
    *SEARCH_DEFINITIONS,
    ToolDefinition(
        "get_article",
        "按search_content返回的article_id读取原文和来源；不能传evidence_id。",
        EntityInput.model_json_schema(),
    ),
    ToolDefinition(
        "get_place_facts",
        "按search_places返回的place_id读取属性；不能传evidence_id；缺字段保持未知。",
        EntityInput.model_json_schema(),
    ),
    ToolDefinition(
        "update_travel_request",
        "只记录用户明确表达的条件；set/clear，必须检查expected_revision。",
        RequestPatch.model_json_schema(),
        kind="state",
    ),
    ToolDefinition(
        "load_skill",
        "按白名单加载业务步骤；文本不授予额外工具权限。",
        SkillInput.model_json_schema(),
    ),
    ToolDefinition(
        "search_hotel_offers",
        "按当前已确认且完整的入住条件查询模拟酒店；返回报价和有效期。",
        HotelSearchInput.model_json_schema(),
    ),
    ToolDefinition(
        "refresh_hotel_offer",
        "为本会话查到过的报价按当前条件重新报价；不沿用旧价格。",
        RefreshOfferInput.model_json_schema(),
    ),
    ToolDefinition(
        "estimate_routes",
        "按当前交通方式查询自制路段估算；起终点用当前place证据ID，未覆盖保持unknown。",
        RouteInput.model_json_schema(),
    ),
    ToolDefinition(
        "validate_itinerary",
        "检查引用证据的行程；冲突需修正，未知保留警告。首次校验后最多修复3轮，不能改写报告。",
        ItineraryProposal.model_json_schema(),
    ),
    ToolDefinition(
        "stage_plan_change",
        "暂存初始行程或稳定item_id的局部patch，返回差异与校验；不保存正式版本，不接受锁定项改动。",
        StageInput.model_json_schema(),
        kind="draft",
    ),
    ToolDefinition(
        "get_saved_plan",
        "读取本会话正式行程、稳定item_id与锁定标记；历史证据需要刷新，不能当当前事实。",
        PlanInput.model_json_schema(),
    ),
    ToolDefinition(
        "hold_hotel",
        "暂留本人本会话查询到的有效完整模拟报价；返回预订ID与到期时间，不能下单，用户必须在页面确认。",
        HoldHotelInput.model_json_schema(),
        kind="state",
    ),
    ToolDefinition(
        "present_travel_result",
        "按本会话报价或草稿ID补卡；行程展示前重新校验，不接受模型提供事实或校验结果。",
        PresentationInput.model_json_schema(),
        kind="presentation",
    ),
)
SCHEMAS: dict[str, type[BaseModel]] = {
    "search_places": PlaceSearchInput,
    "search_content": ContentSearchInput,
    "get_article": EntityInput,
    "get_place_facts": EntityInput,
    "update_travel_request": RequestPatch,
    "load_skill": SkillInput,
    "search_hotel_offers": HotelSearchInput,
    "refresh_hotel_offer": RefreshOfferInput,
    "present_travel_result": PresentationInput,
    "estimate_routes": RouteInput,
    "validate_itinerary": ItineraryProposal,
    "stage_plan_change": StageInput,
    "get_saved_plan": PlanInput,
    "hold_hotel": HoldHotelInput,
}


class TravelToolExecutor:
    def __init__(self, travel: TravelService, *, max_calls: int = 16) -> None:
        self.travel, self.catalog = travel, CatalogService(travel)
        self.hotels = HotelService(travel)
        self.planning = PlanningService(travel)
        self.plans = PlanService(travel)
        self.bookings = BookingService(travel)
        self.calls, self.max_calls = 0, max_calls
        self.validations = 0
        self.last_validation: ItineraryProposal | None = None
        self.loaded_skills: set[str] = set()
        # 第一版全部串行（读并发上限1），避免为尚不存在的并行收益实现读写锁。
        self.lock = asyncio.Lock()
        self.context: RunContext | None = None

    async def execute(
        self, context: RunContext, name: str, arguments: dict[str, object]
    ) -> ToolResult:
        definition = next((d for d in DEFINITIONS if d.name == name), None)
        if definition is None:
            return ToolResult({}, code="blocked", suggestion="请选择已注册的旅行工具")
        async with self.lock:
            if self.context is not None and self.context != context:
                return ToolResult({}, code="blocked", suggestion="执行器不能跨run或用户复用")
            self.context = context
            if self.calls >= self.max_calls:
                return ToolResult({}, code="blocked", suggestion="本轮工具次数已达上限")
            self.calls += 1
            try:
                parsed = SCHEMAS[name].model_validate(arguments)
                async with asyncio.timeout(definition.timeout_seconds):
                    result = await self._dispatch(context, name, parsed)
                if (
                    len(json.dumps(result.payload(), ensure_ascii=False))
                    > definition.max_result_chars
                ):
                    return ToolResult(
                        {}, code="blocked", suggestion="结果过长，请缩小limit或查询范围"
                    )
                return result
            except ValidationError:
                return ToolResult(
                    {}, code="validation", suggestion="检查工具参数；不接受用户/会话身份字段"
                )
            except ServiceError as error:
                return ToolResult({}, code=error.code, suggestion=str(error))
            except TimeoutError:
                return ToolResult({}, code="timeout", suggestion="本轮工具执行超时")
            except (OSError, ValueError):
                return ToolResult({}, code="unavailable", suggestion="本地业务数据暂不可用")

    async def _dispatch(self, context: RunContext, name: str, parsed: BaseModel) -> ToolResult:
        if isinstance(parsed, HoldHotelInput):
            booking = await self.bookings.hold(context, parsed)
            return ToolResult(
                booking.card(),
                evidence_ids=(str(booking.evidence_id),),
                warnings=("仅模拟暂留，不是订单；只允许用户在页面独立确认预订",),
            )
        if isinstance(parsed, StageInput):
            draft = await self.plans.stage(
                context,
                parsed,
                before_validate=lambda proposal: self._take_validation(proposal, staging=True),
            )
            return ToolResult(draft.summary())
        if isinstance(parsed, PlanInput):
            data = await self.plans.get(
                context.user_id, parsed.plan_id, session_id=context.session_id
            )
            return bounded_plan(ToolResult(data))
        if isinstance(parsed, PresentationInput) and parsed.component == "itinerary":
            assert parsed.draft_id is not None
            data = await self.plans.get_draft(
                context.user_id, parsed.draft_id, session_id=context.session_id
            )
            return bounded_plan(
                ToolResult(
                    data, warnings=("草稿尚未确认，unknown仍未核实；仅用户确认API能正式保存",)
                )
            )
        if isinstance(parsed, RouteInput):
            records = await self.planning.routes(context, parsed)
            return ToolResult(
                {
                    "routes": [
                        {
                            **record.value,
                            "evidence_id": str(record.evidence_id),
                            "source_ref": record.source_ref,
                            "content_version": record.content_version,
                        }
                        for record in records
                        if isinstance(record.value, dict)
                    ]
                },
                evidence_ids=tuple(str(record.evidence_id) for record in records),
                warnings=("自制双向路段估算，非实时路线或票价；费用按全员估算，无儿童折扣",),
            )
        if isinstance(parsed, ItineraryProposal):
            self._take_validation(parsed)
            report = await self.planning.validate(context, parsed)
            self.last_validation = parsed
            return ToolResult(
                {**report.feedback(), "repair_rounds_remaining": 4 - self.validations}
            )
        if isinstance(parsed, HotelSearchInput | RefreshOfferInput | PresentationInput):
            return await self._hotel_result(context, parsed)
        if isinstance(parsed, RequestPatch):
            update = await self.travel.patch_request(context, parsed)
            return ToolResult(
                {
                    "request_revision": update.request.revision,
                    "hotel_requirements": update.request.hotel_requirements(),
                    "changed_fields": update.changed_fields,
                }
            )
        if isinstance(parsed, SkillInput):
            await self.travel.get_request(context)
            if parsed.name in self.loaded_skills:
                return ToolResult({"name": parsed.name, "already_loaded": True})
            text = (Path(__file__).resolve().parent / "skills" / (parsed.name + ".md")).read_text(
                encoding="utf-8"
            )
            self.loaded_skills.add(parsed.name)
            return ToolResult(
                {
                    "name": parsed.name,
                    "version": hashlib.sha256(text.encode()).hexdigest(),
                    "instructions": text,
                }
            )
        if isinstance(parsed, ContentSearchInput):
            result = await self.catalog.query(context, parsed)
        else:
            assert isinstance(parsed, EntityInput)
            collection = "places" if name == "get_place_facts" else "articles"
            result = await self.catalog.get(context, collection, parsed.entity_id)
        return catalog_result(result, summary=isinstance(parsed, ContentSearchInput))

    def _take_validation(self, proposal: ItineraryProposal, *, staging: bool = False) -> None:
        # 不变量：最后已校验候选仍可暂存并重新检查，不增加修复次数。
        if staging and proposal == self.last_validation:
            self.last_validation = None
            return
        if self.validations >= 4:
            raise ServiceError(429, "blocked", "首次校验和3轮修复已用完，请说明仍存冲突或未知")
        self.validations += 1

    async def _hotel_result(
        self,
        context: RunContext,
        parsed: HotelSearchInput | RefreshOfferInput | PresentationInput,
    ) -> ToolResult:
        warning = ("虚构酒店与模拟价格，非实时库存；仅住宿成本，不代表全程预算满足",)
        if isinstance(parsed, PresentationInput):
            assert parsed.expected_revision is not None
            data = await self.hotels.present(context, parsed.expected_revision, parsed.offer_ids)
            presented = data["cards"]
            assert isinstance(presented, list)
            return ToolResult(
                data,
                evidence_ids=tuple(str(card["evidence_id"]) for card in presented),
                warnings=warning,
            )
        records = (
            await self.hotels.search(
                context, parsed.expected_revision, parsed.hotel_id, parsed.limit
            )
            if isinstance(parsed, HotelSearchInput)
            else await self.hotels.refresh(context, parsed.expected_revision, parsed.offer_id)
        )
        return ToolResult(
            {"offers": cards(records)},
            empty=not records,
            evidence_ids=tuple(str(record.evidence_id) for record in records),
            warnings=warning,
        )


def catalog_result(result: CatalogResult, *, summary: bool = False) -> ToolResult:
    rows = [
        {
            **(catalog_summary(row) if summary else row),
            "evidence_id": str(record.evidence_id),
            "evidence_status": record.status,
        }
        for row, record in zip(result.rows, result.evidence, strict=True)
    ]
    return ToolResult(
        {result.collection: rows},
        empty=not rows,
        data_mode="snapshot",
        evidence_ids=tuple(str(e.evidence_id) for e in result.evidence),
        warnings=("历史快照非实时事实；缺失字段未知；证据可追溯不等于信息已实时核实",),
    )


def catalog_summary(row: dict[str, object]) -> dict[str, object]:
    """搜索返回ID/来源与短摘要；完整字段和逐字段来源仍在PG，由详情工具读取。"""
    fields = {
        "city",
        "place_id",
        "article_id",
        "name",
        "title",
        "category",
        "latitude",
        "longitude",
        "coordinate_kind",
        "indoor",
        "source",
    }
    result = {key: value for key, value in row.items() if key in fields}
    text = row.get("text")
    if isinstance(text, str):
        result.update(text=text[:600], text_truncated=len(text) > 600)
    return result


def bounded_plan(result: ToolResult) -> ToolResult:
    data = dict(result.data)
    for key, limit in (("cards", 8), ("changes", 6)):
        values = data.get(key)
        if isinstance(values, list):
            data[key] = values[:limit]
            data[key + "_count"] = len(values)
            data[key + "_truncated"] = len(values) > limit
    bounded = replace(result, data=data)
    # 先缩详细差异，再缩卡片；ID/总数/校验警告保留，页面API仍可读取完整内容。
    while len(json.dumps(bounded.payload(), ensure_ascii=False)) > RESULT_LIMIT:
        changes = data.get("changes")
        key = "changes" if isinstance(changes, list) and changes else "cards"
        values = data.get(key)
        if not isinstance(values, list) or len(values) <= (1 if key == "cards" else 0):
            break
        data[key] = values[:-1]
        data[key + "_truncated"] = True
    return bounded
