"""旅行工具的固定注册表与执行边界；SDK负责选工具，这里只验证和调用业务服务。"""

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from backend.domain.execution import RunContext
from backend.domain.travel_request import RequestPatch
from backend.services.catalog import CatalogResult, CatalogService
from backend.services.common import ServiceError
from backend.services.hotels import HotelService, cards
from backend.services.travel import TravelService
from backend.tools.contracts import ToolDefinition, ToolResult
from backend.tools.search import DEFINITIONS as SEARCH_DEFINITIONS
from backend.tools.search import ContentSearchInput, PlaceSearchInput


class EntityInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    entity_id: str = Field(min_length=1, max_length=100)


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
    component: Literal["hotel_comparison"]
    expected_revision: int = Field(strict=True, ge=0)
    offer_ids: tuple[UUID, ...] = Field(min_length=1, max_length=6)

    @field_validator("offer_ids")
    @classmethod
    def unique_ids(cls, ids: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(ids) != len(set(ids)):
            raise ValueError("报价ID不能重复")
        return ids


DEFINITIONS = (
    *SEARCH_DEFINITIONS,
    ToolDefinition(
        "get_article",
        "按search_content返回的article_id读取原文和来源。",
        EntityInput.model_json_schema(),
    ),
    ToolDefinition(
        "get_place_facts",
        "按search_places返回的place_id读取属性；缺字段保持未知。",
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
        "present_travel_result",
        "只提供本会话的报价ID；服务端补齐卡片并比较含税费总价。",
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
}


class TravelToolExecutor:
    def __init__(self, travel: TravelService, *, max_calls: int = 16) -> None:
        self.travel, self.catalog = travel, CatalogService(travel)
        self.hotels = HotelService(travel)
        self.calls, self.max_calls = 0, max_calls
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
        return catalog_result(result)

    async def _hotel_result(
        self,
        context: RunContext,
        parsed: HotelSearchInput | RefreshOfferInput | PresentationInput,
    ) -> ToolResult:
        warning = ("虚构酒店与模拟价格，非实时库存；仅住宿成本，不代表全程预算满足",)
        if isinstance(parsed, PresentationInput):
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


def catalog_result(result: CatalogResult) -> ToolResult:
    rows = [
        {**row, "evidence_id": str(record.evidence_id), "evidence_status": record.status}
        for row, record in zip(result.rows, result.evidence, strict=True)
    ]
    return ToolResult(
        {result.collection: rows},
        empty=not rows,
        data_mode="snapshot",
        evidence_ids=tuple(str(e.evidence_id) for e in result.evidence),
        warnings=("历史快照非实时事实；缺失字段未知；证据可追溯不等于信息已实时核实",),
    )
