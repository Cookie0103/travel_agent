"""P74/R13：住宿查询地点独立、证据失效范围与安全反馈。"""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from backend.domain.conversation import ConversationState, conversation_view
from backend.domain.evidence import evidence_conditions
from backend.domain.travel_request import (
    RequestPatch,
    TravelRequest,
    apply_request_patch,
    invalidated_kinds,
    legacy_request,
)
from backend.tools.contracts import ToolResult
from backend.tools.execution import empty_hotel_payload
from tests.test_travel_request import _record


def test_live_broad_destination_requires_hotel_location_but_not_fixture() -> None:
    request = TravelRequest(
        city="冲绳",
        adults=1,
        rooms=1,
        child_ages=(),
        start_date=date(2026, 10, 11),
        end_date=date(2026, 10, 12),
        hard_constraints=("住宿：独立房间", "房型：禁烟", "床型：大床"),
    )
    state = ConversationState(
        pending_tasks=("hotel_comparison",), awaiting_field="hotel_search_location"
    )
    view = conversation_view(state, request, live_hotels=True)
    assert view["missing_fields"] == ["hotel_search_location"]
    assert view["awaiting_field"] == "hotel_search_location" and view["ready_tasks"] == []
    assert conversation_view(state, request)["ready_tasks"] == ["hotel_comparison"]
    updated, _ = apply_request_patch(
        request,
        RequestPatch.model_validate(
            {"expected_revision": 0, "set": {"hotel_search_location": "那霸"}}
        ),
    )
    assert updated.city == "冲绳" and updated.lodging_budget is None
    assert conversation_view(state, updated, live_hotels=True)["ready_tasks"] == [
        "hotel_comparison"
    ]
    broad = updated.model_copy(update={"hotel_search_location": "沖縄県"})
    assert conversation_view(state, broad, live_hotels=True)["missing_fields"] == [
        "hotel_search_location"
    ]


def test_hotel_location_change_invalidates_only_hotel_and_destination_change_clears_it() -> None:
    request = TravelRequest(city="冲绳", hotel_search_location="那霸", revision=1)
    updated, changed = apply_request_patch(
        request,
        RequestPatch.model_validate(
            {"expected_revision": 1, "set": {"hotel_search_location": "北谷"}}
        ),
    )
    assert changed == {"hotel_search_location"} and invalidated_kinds(changed) == {"hotel_offer"}
    now = datetime.now(UTC)
    assert not _record(request, "hotel_offer", now).applicable(updated, now)
    assert _record(request, "route", now).applicable(updated, now)
    moved, changed = apply_request_patch(
        updated, RequestPatch.model_validate({"expected_revision": 2, "set": {"city": "北海道"}})
    )
    assert moved.hotel_search_location is None and changed == {"city", "hotel_search_location"}
    both, _ = apply_request_patch(
        updated,
        RequestPatch.model_validate(
            {"expected_revision": 2, "set": {"city": "北海道", "hotel_search_location": "札幌"}}
        ),
    )
    assert both.hotel_search_location == "札幌"
    assert "hotel_search_location" not in legacy_request(both)
    assert "hotel_search_location" not in evidence_conditions(moved, "hotel_offer")


@pytest.mark.parametrize("value", ["", " " * 3, "x" * 41, None])
def test_invalid_hotel_location_patch_cannot_overwrite_facts(value: object) -> None:
    with pytest.raises(ValidationError):
        RequestPatch.model_validate(
            {"expected_revision": 0, "set": {"hotel_search_location": value}}
        )


def test_hotel_location_panel_keeps_specific_safe_reason_without_raw_suggestion() -> None:
    result = ToolResult(
        {},
        code="validation",
        suggestion="synthetic-private-input",
        detail=("service:422", "hotel_search_location_required"),
    )
    payload = empty_hotel_payload(result)
    assert "synthetic-private-input" not in str(payload)
    assert "具体住宿城市或地点" in str(payload)
    data = payload["data"]
    assert isinstance(data, dict) and data["cards"] == []
    generic = empty_hotel_payload(
        ToolResult(
            {}, code="validation", suggestion="private", detail=("hotel_external_validation",)
        )
    )
    assert "具体住宿城市或地点" not in str(generic) and "private" not in str(generic)
