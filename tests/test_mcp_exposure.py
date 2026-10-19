"""E5：对外MCP暴露集合与工具kind一致；新增工具必须先登记分类，写类永不对外。"""

import pytest

from backend.mcp import server
from backend.tools.travel import DEFINITIONS

# 全部工具的分类快照：新增工具不在此表则测试失败，逼作者决定kind以及是否对外。
KINDS = {
    "search_places": "read",
    "search_content": "read",
    "get_article": "read",
    "get_place_facts": "read",
    "get_weather_forecast": "read",
    "load_skill": "read",
    "search_hotel_offers": "read",
    "refresh_hotel_offer": "read",
    "estimate_routes": "read",
    "validate_itinerary": "read",
    "get_saved_plan": "read",
    "propose_memory": "state",
    "update_travel_request": "state",
    "update_conversation_state": "state",
    "hold_hotel": "state",
    "stage_plan_change": "draft",
    "present_travel_result": "presentation",
    "present_form": "presentation",
}


def test_every_registered_tool_is_classified() -> None:
    assert {d.name: d.kind for d in DEFINITIONS} == KINDS


def test_external_mcp_exposes_only_read_kind_tools() -> None:
    exposed = {d.name for d in server.READ_ONLY}
    assert exposed == set(server.EXTERNAL_TOOLS)
    assert all(d.kind == "read" for d in server.READ_ONLY)
    writers = {d.name for d in DEFINITIONS if d.kind != "read"}
    assert writers and not writers & exposed


def test_exposing_a_write_or_unknown_tool_is_refused() -> None:
    for name in ("hold_hotel", "stage_plan_change", "update_travel_request", "no_such_tool"):
        with pytest.raises(RuntimeError, match="kind=read"):
            server.read_only_tools((*server.EXTERNAL_TOOLS, name))
