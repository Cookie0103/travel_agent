"""旅行工具的固定注册表与执行边界；SDK负责选工具，这里只验证和调用业务服务。"""

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy.exc import SQLAlchemyError

from backend.adapters.live_data import LiveData
from backend.adapters.open_meteo import forecast
from backend.domain.booking import HoldHotelInput
from backend.domain.condition_labels import update_message
from backend.domain.conversation import ConversationStateInput
from backend.domain.execution import RunContext
from backend.domain.external_data import ExternalDataError
from backend.domain.hotel_details import HotelDisplayDetails
from backend.domain.itinerary import ItineraryProposal, RouteInput, ValidationReport
from backend.domain.plans import StageInput
from backend.domain.room_choices import room_choices_view
from backend.domain.travel_request import (
    ConversationRequestPatch,
    RequestPatch,
    lodging_budget_relation,
)
from backend.services.bookings import BookingService
from backend.services.catalog import CatalogResult, CatalogService
from backend.services.common import ServiceError
from backend.services.hotels import HotelService, cards
from backend.services.planning import PlanningService
from backend.services.plans import PlanInput, PlanService
from backend.services.travel import TravelService, require_revision
from backend.tools.contracts import (
    RESULT_LIMIT,
    ToolDefinition,
    ToolResult,
    validation_paths,
    with_repair_rounds,
)
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
    limit: int = Field(
        default=4,
        strict=True,
        ge=1,
        le=6,
        description="不同酒店数；全结果最多6条报价，每家最多2套餐",
    )


class WeatherInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_revision: int = Field(strict=True, ge=0)


class RefreshOfferInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_revision: int = Field(strict=True, ge=0)
    offer_id: UUID


class PresentationInput(BaseModel):
    """酒店比较填component=hotel_comparison、expected_revision和offer_ids；行程只填component=itinerary和stage返回的draft_id。两类参数不得混填。offer_ids填酒店卡片的offer_id；行程的hotel_evidence_id填卡片的evidence_id。"""

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
        "get_weather_forecast",
        "按当前条件的城市与日期查询每日天气；超过16天或未定日期返回unknown。",
        WeatherInput.model_json_schema(),
    ),
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
        "只记录用户明确表达的条件；set/clear，必须检查expected_revision。"
        "全程budget与lodging_budget原值同时保留；后者是住宿分项，注明区间/口径/币种。"
        "每轮提取用户说出的目的地/日期/同行者/房间/两预算/节奏，不要求先填右侧。"
        "手填值优先；明确改成新值的字段列入explicit_fields，模糊提取不要列入。"
        "回执skipped_fields未更新，必须追问；实际更新向用户告知回执message。"
        "房型优先用room_preferences严格枚举：lodging=private/dorm/capsule/any，smoking=nonsmoking/any，bed=twin/double/any；无要求用any，未提项省略。"
        "hard_constraints保留未提项，只替换本次房型组；明确删除用remove_hard_constraints列出当前旧文本，并声明explicit_fields=hard_constraints。"
        "省级目的地需要住宿地点时，set.hotel_search_location记录用户明确地点，保留city；机场起终点不等于住宿地点，不默认选择那霸。"
        "返回预算冲突时先追问以哪个为准，回答后只改用户指定字段，不比较酒店。",
        ConversationRequestPatch.model_json_schema(),
        kind="state",
    ),
    ToolDefinition(
        "update_conversation_state",
        "记录用户明确授权的酒店比较/完整行程目标(goals)，后续澄清不重设goals。追问前记录唯一awaiting_field；只能问服务端missing_fields。用户取消用cancel。不能自报完成；实际查询展示后服务端自动推进。元数据不增旅行revision。",
        ConversationStateInput.model_json_schema(),
        kind="state",
    ),
    ToolDefinition(
        "load_skill",
        "按白名单加载业务步骤；文本不授予额外工具权限。",
        SkillInput.model_json_schema(),
    ),
    ToolDefinition(
        "search_hotel_offers",
        "按当前完整入住条件查询不同酒店（limit为酒店数）；整体最多6报价，每家最多2套餐，保持上游顺序。实时模式逐晚核算乐天含税报价，未知不猜测。每张卡的offer_id用于present/refresh，evidence_id用于行程hotel_evidence_id。",
        HotelSearchInput.model_json_schema(),
    ),
    ToolDefinition(
        "refresh_hotel_offer",
        "为本会话查到过的报价按当前条件重新报价；不沿用旧价格。",
        RefreshOfferInput.model_json_schema(),
    ),
    ToolDefinition(
        "estimate_routes",
        (
            "按当前交通方式查询自制路段估算；起终点用当前place证据ID，未覆盖保持unknown。"
            "先定好各项时间，再按行程顺序逐段估算（每次最多6段），每段departure取前一项结束时间，"
            "须介于前一项结束与后一项开始之间；每天首项不接路段，不要给它route_evidence_id；"
            "调整顺序或时间后，对受影响的相邻项重新估算。"
        ),
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
        "暂留本人本会话查询到的有效完整模拟报价；重复同一报价返回已有预订状态，不创建第二条。"
        "返回预订ID与到期时间，不能下单，用户必须在页面确认。",
        HoldHotelInput.model_json_schema(),
        kind="state",
    ),
    ToolDefinition(
        "present_travel_result",
        (PresentationInput.__doc__ or "")
        + "按本会话报价或草稿ID补卡；行程展示前重新校验，不接受模型提供事实或校验结果。",
        PresentationInput.model_json_schema(),
        kind="presentation",
    ),
)
SCHEMAS: dict[str, type[BaseModel]] = {
    "get_weather_forecast": WeatherInput,
    "search_places": PlaceSearchInput,
    "search_content": ContentSearchInput,
    "get_article": EntityInput,
    "get_place_facts": EntityInput,
    "update_travel_request": ConversationRequestPatch,
    "update_conversation_state": ConversationStateInput,
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


LIVE_TOOL_TIMEOUT = 75


def repair_definitions(
    definitions: tuple[ToolDefinition, ...], max_validations: int
) -> tuple[ToolDefinition, ...]:
    """模型可见的修复轮数随档位；DEFINITIONS本身(基准/指纹)不变。"""
    return tuple(
        replace(d, description=with_repair_rounds(d.description, max_validations))
        if d.name == "validate_itinerary"
        else d
        for d in definitions
    )


def live_definitions(definitions: tuple[ToolDefinition, ...]) -> tuple[ToolDefinition, ...]:
    return tuple(
        replace(definition, timeout_seconds=LIVE_TOOL_TIMEOUT)
        if definition.name
        in {
            "search_hotel_offers",
            "refresh_hotel_offer",
            "estimate_routes",
            "present_travel_result",
            "stage_plan_change",
            "validate_itinerary",
            "get_saved_plan",
            "search_places",
            "get_place_facts",
            "get_weather_forecast",
        }
        else definition
        for definition in definitions
        if definition.name != "hold_hotel"
    )


def report_detail(report: ValidationReport) -> tuple[str, ...]:
    """校验报告 -> 状态、各状态计数、未通过检查的code:status(不含名称/文案)。"""
    counts = {
        s: sum(c.status == s for c in report.checks) for s in ("verified", "unknown", "conflict")
    }
    worst = sorted(
        (c for c in report.checks if c.status != "verified"),
        key=lambda c: c.status != "conflict",
    )
    return (
        f"report:{report.status}",
        "counts:" + "/".join(f"{k[0]}{v}" for k, v in counts.items()),
        *(c.trace_label for c in worst[:5]),
    )


MAX_VALIDATIONS_CAP = 50  # 构造上限，与HUMAN档一致；更大值只能是配置错误


class TravelToolExecutor:
    def __init__(
        self,
        travel: TravelService,
        *,
        live: LiveData | None = None,
        max_calls: int = 16,
        max_validations: int = 4,
    ) -> None:
        if type(max_validations) is not int or not 1 <= max_validations <= MAX_VALIDATIONS_CAP:
            raise ValueError("校验次数只允许1(单因素首次)到档位上限")
        if live is not None:
            travel.live = live
        self.travel, self.catalog = travel, CatalogService(travel)
        self.hotels = HotelService(travel)
        self.planning = PlanningService(travel)
        self.plans = PlanService(travel)
        self.bookings = BookingService(travel)
        self.calls, self.max_calls = 0, max_calls
        self.validations = 0
        self.max_validations = max_validations
        self.last_validation: ItineraryProposal | None = None
        self.loaded_skills: set[str] = set()
        # 第一版全部串行（读并发上限1），避免为尚不存在的并行收益实现读写锁。
        self.lock = asyncio.Lock()
        self.context: RunContext | None = None
        self.stopping_error = False

    async def execute(
        self, context: RunContext, name: str, arguments: dict[str, object]
    ) -> ToolResult:
        result = await self._execute(context, name, arguments)
        if name != "get_weather_forecast" and result.code in {
            "unavailable",
            "timeout",
            "blocked",
            "rate_limited",
            "cancelled",
            "provider_error",
        }:
            self.stopping_error = True
        if name in {"validate_itinerary", "stage_plan_change"}:
            # 每次校验调用都记录修复轮次(含被拒绝的调用)。
            rounds = (f"repair_round:{self.validations}", f"max_validations:{self.max_validations}")
            result = replace(result, detail=(*result.detail, *rounds))
        return result

    async def _execute(
        self, context: RunContext, name: str, arguments: dict[str, object]
    ) -> ToolResult:
        definitions = live_definitions(DEFINITIONS) if self.travel.live else DEFINITIONS
        definition = next((d for d in definitions if d.name == name), None)
        if definition is None:
            return ToolResult(
                {},
                code="blocked",
                suggestion="请选择已注册的旅行工具",
                detail=("unregistered_tool",),
            )
        async with self.lock:
            if self.context is not None and self.context != context:
                return ToolResult(
                    {},
                    code="blocked",
                    suggestion="执行器不能跨run或用户复用",
                    detail=("context_reuse",),
                )
            self.context = context
            if self.calls >= self.max_calls:
                return ToolResult(
                    {}, code="blocked", suggestion="本轮工具次数已达上限", detail=("tool_call_cap",)
                )
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
                        {},
                        code="blocked",
                        suggestion="结果过长，请缩小limit或查询范围",
                        detail=("result_too_long",),
                    )
                if result.code is None:
                    if isinstance(parsed, PresentationInput):
                        revision = (
                            parsed.expected_revision
                            if parsed.component == "hotel_comparison"
                            else result.data.get("request_revision")
                        )
                        assert isinstance(revision, int)
                        await self.travel.complete_conversation_task(
                            context, parsed.component, revision
                        )
                    elif isinstance(parsed, HotelSearchInput | RefreshOfferInput) and result.empty:
                        await self.travel.complete_conversation_task(
                            context, "hotel_comparison", parsed.expected_revision
                        )
                return result
            except ValidationError as error:
                if any(
                    item["type"] == "timezone_aware"
                    for item in error.errors(include_input=False, include_context=False)
                ):
                    return ToolResult(
                        {},
                        code="validation",
                        suggestion="日期时间必须带时区；京都当地时间使用+09:00",
                        detail=("schema", *validation_paths(error)),
                    )
                return ToolResult(
                    {},
                    code="validation",
                    suggestion=(PresentationInput.__doc__ or "检查工具参数")
                    if name == "present_travel_result"
                    else "由模型修正参数，不向用户重复追问已知条件：room_preferences仅用枚举，"
                    "未提组省略，无要求用any，不传null；房型明确改值的explicit_fields填"
                    "['hard_constraints']（不是bed或room_preferences）；set/clear不得重叠，"
                    "typed房型与hard_constraints不得矛盾。"
                    if name == "update_travel_request"
                    else "检查工具参数；不接受用户/会话身份字段",
                    detail=("schema", *validation_paths(error)),
                )
            except ServiceError as error:
                return ToolResult(
                    {},
                    code=error.code,
                    suggestion=str(error),
                    detail=(f"service:{error.status}", error.reason or "untagged"),
                )
            except ExternalDataError as error:
                return ToolResult(
                    {},
                    code="validation" if error.validation else "unavailable",
                    suggestion=str(error),
                    detail=("external_data", "validation" if error.validation else "unavailable"),
                )
            except TimeoutError:
                return ToolResult(
                    {}, code="timeout", suggestion="本轮工具执行超时", detail=("tool_timeout",)
                )
            except (OSError, ValueError, SQLAlchemyError) as error:
                return ToolResult(
                    {},
                    code="unavailable",
                    suggestion="本地业务数据暂不可用",
                    detail=("local_error", type(error).__name__),
                )

    async def _dispatch(self, context: RunContext, name: str, parsed: BaseModel) -> ToolResult:
        if isinstance(parsed, ConversationStateInput):
            return ToolResult(await self.travel.update_conversation_state(context, parsed))
        if isinstance(parsed, WeatherInput):
            request = await self.travel.get_request(context)
            require_revision(request, parsed.expected_revision)
            live = self.travel.live
            if not live:
                return ToolResult({}, code="unavailable", suggestion="离线模式不提供天气")
            if not live.google or not request.city:
                return ToolResult({}, code="validation", suggestion="请先指定城市并配置Google API")
            point = await live.google.geocode(request.city)
            return ToolResult(
                await forecast(live.http, live.usage, point, request), data_mode="live"
            )
        if isinstance(parsed, HoldHotelInput):
            if self.travel.live:
                raise ServiceError(
                    403,
                    "blocked",
                    "实时酒店只支持查询和乐天链接，不暂留或下单",
                    "live_hold_disabled",
                )
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
            return ToolResult(
                draft.summary(),
                detail=report_detail(draft.validation),
            )
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
                data_mode="live" if self.travel.live else "fixture",
                warnings=("Google Maps 路线查询，未知时长/票价不猜测",)
                if self.travel.live
                else ("自制双向路段估算，非实时路线或票价；费用按全员估算，无儿童折扣",),
            )
        if isinstance(parsed, ItineraryProposal):
            self._take_validation(parsed)
            report = await self.planning.validate(context, parsed)
            self.last_validation = parsed
            return ToolResult(
                {
                    **report.feedback(),
                    "repair_rounds_remaining": self.max_validations - self.validations,
                },
                detail=report_detail(report),
            )
        if isinstance(parsed, HotelSearchInput | RefreshOfferInput | PresentationInput):
            return await self._hotel_result(context, parsed)
        if isinstance(parsed, RequestPatch):
            assert isinstance(parsed, ConversationRequestPatch)
            update = await self.travel.patch_request(
                context,
                parsed,
                source="conversation",
                explicit_fields=parsed.explicit_fields,
            )
            return ToolResult(
                {
                    "request_revision": update.request.revision,
                    "room_preferences": room_choices_view(update.request.hard_constraints),
                    "conversation": (await self.travel.business_context(context))["conversation"],
                    "budget_relation": lodging_budget_relation(update.request).model_dump(
                        mode="json"
                    ),
                    "hotel_requirements": update.request.hotel_requirements(),
                    "changed_fields": update.changed_fields,
                    "skipped_fields": update.skipped_fields,
                    "field_sources": update.field_sources,
                    "message": update_message(
                        update.request, update.changed_fields, update.skipped_fields
                    ),
                }
            )
        if isinstance(parsed, SkillInput):
            await self.travel.get_request(context)
            if parsed.name in self.loaded_skills:
                return ToolResult({"name": parsed.name, "already_loaded": True})
            text = with_repair_rounds(
                (Path(__file__).resolve().parent / "skills" / (parsed.name + ".md")).read_text(
                    encoding="utf-8"
                ),
                self.max_validations,
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
        if self.validations >= self.max_validations:
            message = (
                "本次评测仅允许首次校验，不再修复；请说明仍存冲突或未知"
                if self.max_validations == 1
                else f"首次校验和{self.max_validations - 1}轮修复已用完，请说明仍存冲突或未知"
            )
            raise ServiceError(429, "blocked", message, "repair_limit")
        self.validations += 1

    async def _hotel_result(
        self,
        context: RunContext,
        parsed: HotelSearchInput | RefreshOfferInput | PresentationInput,
    ) -> ToolResult:
        warning = (
            ("乐天实时查询，含税和服务费；未知明细不猜测，仅住宿成本，不代表全程预算满足",)
            if self.travel.live
            else ("虚构酒店与模拟价格，非实时库存；仅住宿成本，不代表全程预算满足",)
        )
        if isinstance(parsed, PresentationInput):
            assert parsed.expected_revision is not None
            data = await self.hotels.present(context, parsed.expected_revision, parsed.offer_ids)
            presented = data["cards"]
            assert isinstance(presented, list)
            # 可选展示字段为null时省略给工具/页面的重复键；报价身份/金额/资格信息保留。
            # 完整服务读回仍保留显式null，UI模型默认值兼容旧卡；不提高输出长度上限。
            data["cards"] = [
                {
                    key: value
                    for key, value in card.items()
                    if value is not None or key not in HotelDisplayDetails.model_fields
                }
                for card in presented
            ]
            return ToolResult(
                data,
                evidence_ids=tuple(str(card["evidence_id"]) for card in presented),
                warnings=warning,
                data_mode="live" if self.travel.live else "fixture",
            )
        records = (
            await self.hotels.search(
                context, parsed.expected_revision, parsed.hotel_id, parsed.limit
            )
            if isinstance(parsed, HotelSearchInput)
            else await self.hotels.refresh(context, parsed.expected_revision, parsed.offer_id)
        )
        request = await self.travel.get_request(context)
        require_revision(request, parsed.expected_revision)
        offers, trimmed = bounded_offers(cards(records, request), warning)
        return ToolResult(
            {"offers": offers},
            empty=not records,
            evidence_ids=tuple(str(offer["evidence_id"]) for offer in offers),
            warnings=(*warning, TRIMMED_WARNING) if trimmed else warning,
            data_mode="live" if self.travel.live else "fixture",
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
        data_mode="live" if any(e.data_mode == "live" for e in result.evidence) else "snapshot",
        evidence_ids=tuple(str(e.evidence_id) for e in result.evidence),
        warnings=result.warnings
        + (
            ("Google Maps 实时查询，缺失字段仍未知",)
            if any(e.data_mode == "live" for e in result.evidence)
            else ("历史快照非实时事实；缺失字段未知；证据可追溯不等于信息已实时核实",)
        ),
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
        "opening_hours",
        "source",
    }
    result = {key: value for key, value in row.items() if key in fields}
    text = row.get("text")
    if isinstance(text, str):
        result.update(text=text[:600], text_truncated=len(text) > 600)
    return result


TRIMMED_WARNING = "报价过多，按上游顺序保留部分报价；所列数量未必达到要求，可用hotel_id缩小范围"
OFFER_DROP = ("stay", "request_revision", "image_url")  # 同一次查询共用的入住条件/展示字段


def bounded_offers(
    offers: list[dict[str, object]], warning: tuple[str, ...]
) -> tuple[list[dict[str, object]], bool]:
    """去重复展示字段，仍超长按上游顺序保留整张卡；不按价格重排或截断JSON。"""
    rows = [{k: v for k, v in offer.items() if k not in OFFER_DROP} for offer in offers]
    kept = len(rows)

    def size(count: int) -> int:
        probe = ToolResult(
            {"offers": rows[:count]},
            evidence_ids=tuple(str(o["evidence_id"]) for o in rows[:count]),
            warnings=(*warning, TRIMMED_WARNING),
        )
        return len(json.dumps(probe.payload(), ensure_ascii=False))

    while kept > 1 and size(kept) > RESULT_LIMIT:
        kept -= 1
    return rows[:kept], kept < len(rows)


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
