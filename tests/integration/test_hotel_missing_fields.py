"""真实PG：房间数从未记录时，酒店查询的失败对用户和模型都点明缺什么。"""

import asyncio

from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.travel_request import RequestPatch
from backend.services.travel import TravelService
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS, TravelToolExecutor
from tests.integration.test_travel import travel_setup as travel_setup


def test_unrecorded_rooms_is_named_to_user_and_model_and_not_defaulted(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, context = travel_setup

    async def exercise() -> None:
        update = await travel.patch_request(
            context,
            RequestPatch.model_validate({"expected_revision": 1, "clear": ["rooms"]}),
        )
        assert update.request.rooms is None and update.request.adults == 2
        events: list[RuntimeEvent] = []
        result = await execute_observed(
            TravelToolExecutor(travel),
            context,
            "search_hotel_offers",
            {"expected_revision": update.request.revision},
            events.append,
            definition=next(d for d in DEFINITIONS if d.name == "search_hotel_offers"),
        )
        assert result.code == "validation" and "missing:rooms" in result.detail
        # 模型侧：具体、可执行，且只含封闭字段名。
        assert "缺少：rooms" in result.suggestion and "update_travel_request" in result.suggestion
        # 步骤原因码具体。
        finished = [e for e in events if e.kind == "tool_finished"][-1]
        assert finished.reason == "hotel_missing_fields"
        # 用户侧：固定中文标签；不默认写入rooms=1。
        panel = str(events[-1].presentation)
        assert "缺少：房间数" in panel and "rooms" not in panel
        assert (await travel.get_request(context)).rooms is None

    runner.run(exercise())
