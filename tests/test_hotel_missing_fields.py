"""酒店查询缺条件：原因码具体，用户面只说固定中文字段名，不回显异常文本。"""

import pytest

from backend.domain.execution import tool_reason
from backend.tools.contracts import ToolResult
from backend.tools.execution import empty_hotel_payload


def rejected(*fields: str) -> ToolResult:
    return ToolResult(
        {},
        code="validation",
        suggestion="synthetic-private-text",
        detail=("service:422", "hotel_missing_fields", *(f"missing:{f}" for f in fields)),
    )


@pytest.mark.parametrize(
    "tag",
    [
        "hotel_missing_fields",
        "hotel_room_preferences_missing",
        "hotel_external_validation",
        "hotel_external_unavailable",
        "hotel_api_unconfigured",
    ],
)
def test_hotel_validation_tags_are_closed_reasons_not_other(tag: str) -> None:
    assert tool_reason("validation", ("service:422", tag)) == tag


def test_user_message_names_missing_fields_in_stable_order_without_raw_text() -> None:
    panel = str(empty_hotel_payload(rejected("rooms", "adults", "start_date")))
    assert "缺少：入住日期、成人人数、房间数" in panel
    assert "synthetic-private-text" not in panel


def test_unknown_or_odd_field_names_are_skipped_never_echoed() -> None:
    panel = str(empty_hotel_payload(rejected("rooms", "<script>x", "passport_no")))
    assert "缺少：房间数" in panel
    assert "script" not in panel and "passport" not in panel
    only_odd = str(empty_hotel_payload(rejected("passport_no")))
    assert "缺少：" not in only_odd and "查询条件或参数尚不完整" in only_odd
