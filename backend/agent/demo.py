"""工作台的三个固定离线样例；只拼旅行工具输入，业务规则全部复用服务端。"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import cast
from uuid import uuid4
from zoneinfo import ZoneInfo

from backend.agent.fixture_conditions import missing_question
from backend.agent.runtime import EventSink
from backend.domain.execution import RunContext, RuntimeEvent, RuntimeOutcome
from backend.domain.plans import PlanItem
from backend.domain.room_preferences import room_preferences_question
from backend.domain.travel_request import TravelRequest
from backend.services.common import ServiceError
from backend.tools.contracts import ToolExecutor, ToolResult
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS, TravelToolExecutor

type DemoCall = Callable[[str, dict[str, object]], Awaitable[ToolResult]]

COMMANDS = ("演示：比较酒店", "演示：生成行程", "演示：修改第二天下午")


async def demo_command(
    executor: ToolExecutor,
    context: RunContext,
    prompt: str,
    emit: EventSink,
    cancelled: asyncio.Event,
) -> RuntimeOutcome:
    if prompt not in COMMANDS or not isinstance(executor, TravelToolExecutor):
        return RuntimeOutcome(code="validation", reason="unsupported_demo")

    async def call(name: str, arguments: dict[str, object]) -> ToolResult:
        if cancelled.is_set():
            raise asyncio.CancelledError
        definition = next(item for item in DEFINITIONS if item.name == name)
        result = await execute_observed(
            executor, context, name, arguments, emit, definition=definition
        )
        if result.empty and not (prompt == COMMANDS[0] and name == "search_hotel_offers"):
            raise ServiceError(422, "unavailable", "演示工具没有可用数据，请检查条件或数据导入")
        if result.code:
            raise ServiceError(422, result.code, result.suggestion or "工具执行失败")
        return result

    try:
        request = await executor.travel.get_request(context)
        if prompt in COMMANDS[:2] and (
            request.hotel_requirements() or room_preferences_question(request)
        ):
            text = (
                missing_question(request)
                if request.hotel_requirements()
                else room_preferences_question(request)
            )
            assert text is not None
            emit(RuntimeEvent(context, "text", text=text))
            return RuntimeOutcome(text, str(uuid4()))
        if prompt in COMMANDS[:2] and request.city != "京都":
            text = f"已保留目的地{request.city}。离线酒店/行程样例仅覆盖京都；不会替换你的目的地。"
            emit(RuntimeEvent(context, "text", text=text))
            return RuntimeOutcome(text, str(uuid4()))
        if prompt == COMMANDS[0]:
            text = await compare_demo(call, request)
        elif prompt == COMMANDS[1]:
            text = await generate_demo(call, request)
        else:
            text = await revise_demo(call, executor, context, request)
    except ServiceError as error:
        emit(RuntimeEvent(context, "text", text=str(error)))
        return RuntimeOutcome(text=str(error), code=error.code, reason="demo_failed")
    emit(RuntimeEvent(context, "text", text=text))
    return RuntimeOutcome(text, str(uuid4()))


async def compare_demo(call: DemoCall, request: TravelRequest) -> str:
    offers = await call("search_hotel_offers", {"expected_revision": request.revision, "limit": 3})
    rows = cast(list[dict[str, object]], offers.data["offers"])
    if not rows:
        return (
            "没有找到符合当前条件的模拟酒店报价。请在对话中调整条件后重试；本轮没有进行价格比较。"
        )
    await call(
        "present_travel_result",
        {
            "component": "hotel_comparison",
            "expected_revision": request.revision,
            "offer_ids": [row["offer_id"] for row in rows],
        },
    )
    text = "离线脚本已比较模拟酒店。价格与结论由服务端计算，非实时库存。"
    return text


async def generate_demo(call: DemoCall, request: TravelRequest) -> str:
    if not request.start_date or not request.end_date:
        raise ServiceError(422, "validation", "请在对话里告诉我旅行的开始与结束日期")
    days = (request.end_date - request.start_date).days + 1
    if not 2 <= days <= 3:
        raise ServiceError(422, "validation", "固定演示仅覆盖京都二至三日游")
    place_ids = []
    for entity in ("osm:way/57111281", "osm:way/554879249"):
        facts = await call("get_place_facts", {"entity_id": entity})
        place_ids.append(facts.evidence_ids[0])
    offers = await call("search_hotel_offers", {"expected_revision": request.revision, "limit": 1})
    items: list[dict[str, object]] = []
    legs: list[dict[str, object]] = []
    for day in range(days):
        date = request.start_date + timedelta(days=day)
        start = datetime.combine(date, datetime.min.time(), ZoneInfo("Asia/Tokyo"))
        legs.append(
            {
                "from_evidence_id": place_ids[0],
                "to_evidence_id": place_ids[1],
                "departure": (start + timedelta(hours=11)).isoformat(),
            }
        )
        for index, hour in enumerate((10, 14)):
            items.append(
                {
                    "place_evidence_id": place_ids[index],
                    "start": (start + timedelta(hours=hour)).isoformat(),
                    "end": (start + timedelta(hours=hour + 1)).isoformat(),
                }
            )
    routes = await call("estimate_routes", {"expected_revision": request.revision, "legs": legs})
    for index, record in enumerate(cast(list[dict[str, object]], routes.data["routes"])):
        items[index * 2 + 1]["route_evidence_id"] = record["evidence_id"]
    staged = await call(
        "stage_plan_change",
        {
            "change": {
                "kind": "initial",
                "proposal": {
                    "expected_revision": request.revision,
                    "items": items,
                    "hotel_evidence_id": offers.evidence_ids[0],
                },
            }
        },
    )
    await call(
        "present_travel_result",
        {"component": "itinerary", "draft_id": staged.data["draft_id"]},
    )
    text = "离线脚本已生成草稿。重复景点用于演示状态流程；未知费用与路线估算仍保留。请检查后确认。"
    return text


async def revise_demo(
    call: DemoCall, executor: TravelToolExecutor, context: RunContext, request: TravelRequest
) -> str:
    business = await executor.travel.business_context(context)
    pointer = business["saved_plan"]
    if not isinstance(pointer, dict):
        raise ServiceError(422, "validation", "请先确认一份正式行程")
    saved = await call("get_saved_plan", {"plan_id": pointer["plan_id"]})
    if saved.data.get("cards_truncated"):
        raise ServiceError(
            422, "validation", "固定演示不能从截断行程判定修改目标；请明确要改的行程项"
        )
    cards = cast(list[dict[str, object]], saved.data["cards"])
    if not request.start_date:
        raise ServiceError(422, "validation", "请先确认开始日期")
    second_day = request.start_date + timedelta(days=1)
    items = [
        PlanItem.model_validate(
            {key: value for key, value in card.items() if key in PlanItem.model_fields}
        )
        for card in cards
    ]
    candidates = [
        item
        for item in items
        if item.start.astimezone(ZoneInfo("Asia/Tokyo")).date() == second_day
        and 12 <= item.start.astimezone(ZoneInfo("Asia/Tokyo")).hour < 18
    ]
    if len(candidates) != 1:
        raise ServiceError(422, "validation", "固定演示需要第二天下午恰好一项；请明确要改的行程项")
    item = candidates[0]
    changed = item.proposed().model_copy(
        update={
            "start": item.start + timedelta(hours=1),
            "end": item.end + timedelta(hours=1),
        }
    )
    staged = await call(
        "stage_plan_change",
        {
            "change": {
                "kind": "patch",
                "plan_id": pointer["plan_id"],
                "patch": {
                    "base_version": saved.data["version"],
                    "expected_revision": request.revision,
                    "operations": [
                        {
                            "op": "update",
                            "item_id": str(item.item_id),
                            "item": changed.model_dump(mode="json"),
                        }
                    ],
                },
            }
        },
    )
    await call(
        "present_travel_result",
        {"component": "itinerary", "draft_id": staged.data["draft_id"]},
    )
    text = "离线脚本只将第二天下午顺延一小时。其余项目和酒店保留，正式版本等待再次确认。"
    return text
