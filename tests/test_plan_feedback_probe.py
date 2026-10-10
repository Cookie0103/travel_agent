"""真实模型探针的离线前置检查；不请求模型或数据库。"""

from pathlib import Path

import pytest

from backend.domain.travel_request import TravelRequest
from scripts import probe_plan_feedback
from scripts.probe_plan_feedback import diagnostic_request, summarize, synthetic_places


def test_diagnostic_places_are_explicitly_synthetic_and_have_closing_hours() -> None:
    places = synthetic_places()
    assert len(places) == 2
    assert all("合成" in p.name and p.opening_hours == "09:00-17:00" for p in places)
    assert all(p.source.source_ref == "fixture:P72-feedback" for p in places)
    assert all(p.field_sources["opening_hours"] == "fixture:P72-feedback" for p in places)


def test_direct_success_does_not_prove_closed_feedback_repair() -> None:
    result = summarize({"status": "success", "events": []})
    assert result["feedback_repaired"] is False
    assert "answer" not in result


def test_repair_requires_conflict_then_successful_validation_stage_and_presentation() -> None:
    traces: list[dict[str, object]] = [
        {
            "ev": "tool_end",
            "name": "validate_itinerary",
            "detail": ["report:conflict", "opening_hours:conflict@d1i2", "counts:v1/u1/c1"],
        },
        {
            "ev": "tool_end",
            "name": "validate_itinerary",
            "detail": ["report:partial", "counts:v3/u1/c0"],
        },
    ]
    traces.extend(
        [
            {"ev": "tool_end", "name": "stage_plan_change", "detail": ["report:partial"]},
            {"ev": "tool_end", "name": "present_travel_result", "detail": []},
        ]
    )
    events: list[dict[str, object]] = [
        {"kind": "tool_finished", "tool_name": "validate_itinerary", "code": None},
        {"kind": "tool_finished", "tool_name": "validate_itinerary", "code": None},
        {
            "kind": "tool_finished",
            "tool_name": "stage_plan_change",
            "code": None,
            "business_result": {
                "kind": "draft_staged",
                "draft_id": "synthetic",
                "validation_status": "partial",
            },
        },
    ]
    events.append({"kind": "tool_finished", "tool_name": "present_travel_result", "code": None})
    report: dict[str, object] = {
        "status": "success",
        "answer": "private synthetic text",
        "events": events,
    }
    assert summarize(report, traces)["feedback_repaired"] is False
    events.append(
        {
            "kind": "presentation",
            "presentation": {
                "data": {
                    "draft_id": "synthetic",
                    "status": "staged",
                    "validation": {"status": "partial"},
                }
            },
        }
    )
    result = summarize(report, traces)
    assert result["feedback_repaired"] is True
    assert "private synthetic text" not in str(result)


def test_synthetic_request_uses_existing_conditions_contract() -> None:
    patch = diagnostic_request()
    assert patch.set_fields.soft_constraints == ("节奏：标准",)
    request = TravelRequest.model_validate(patch.set_fields.model_dump(mode="json"))
    assert request.hotel_requirements() == ()


@pytest.mark.parametrize("status", ["success", "error"])
def test_old_draft_before_closed_validation_cannot_count_as_repair(status: str) -> None:
    traces: list[dict[str, object]] = [
        {"ev": "tool_end", "name": "stage_plan_change", "detail": ["report:partial"]},
        {"ev": "tool_end", "name": "present_travel_result", "detail": []},
        {"ev": "tool_end", "name": "validate_itinerary", "detail": ["opening_hours:conflict@d1i2"]},
        {"ev": "tool_end", "name": "validate_itinerary", "detail": ["report:partial"]},
    ]
    events: list[dict[str, object]] = [
        {
            "kind": "tool_finished",
            "tool_name": "stage_plan_change",
            "code": None,
            "business_result": {
                "kind": "draft_staged",
                "draft_id": "old",
                "validation_status": "partial",
            },
        },
        {"kind": "tool_finished", "tool_name": "present_travel_result", "code": None},
        {
            "kind": "presentation",
            "presentation": {
                "data": {"draft_id": "old", "status": "staged", "validation": {"status": "partial"}}
            },
        },
        {"kind": "tool_finished", "tool_name": "validate_itinerary", "code": None},
        {"kind": "tool_finished", "tool_name": "validate_itinerary", "code": None},
    ]
    assert summarize({"status": status, "events": events}, traces)["feedback_repaired"] is False


def test_live_probe_cannot_repeat_an_already_started_model_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "p72-feedback-probe.started").write_text("already attempted")
    monkeypatch.setattr(probe_plan_feedback, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["probe", "--live"])

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("repeat must stop before setup or model calls")

    monkeypatch.setattr(probe_plan_feedback, "prepare", forbidden)
    monkeypatch.setattr(probe_plan_feedback, "run_live", forbidden)
    assert probe_plan_feedback.main() == 1
