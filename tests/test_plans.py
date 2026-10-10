"""R07：稳定item_id的局部增改删、锁定和未修改字段保留，不靠地点ID批量改写。"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.domain.itinerary import ItineraryProposal, ValidationReport
from backend.domain.plans import (
    PlanContent,
    PlanPatch,
    SavedPlan,
    apply_plan_patch,
    differences,
    initial_content,
)
from backend.domain.travel_request import RequestPatch
from backend.tools.travel import DEFINITIONS
from tests.test_itinerary import item, place, record


@pytest.mark.parametrize("kind", ["proposal", "patch"])
def test_new_hotel_stays_are_readable_but_not_writable_during_compatibility(kind: str) -> None:
    """R07：新住宿payload只允许持久化读取上下文，旧写入契约仍拒绝。"""
    current = saved()
    stay = {
        "check_in": "2026-11-03",
        "check_out": "2026-11-05",
        "hotel_evidence_id": str(uuid4()),
    }
    model: type[ItineraryProposal] | type[PlanPatch]
    if kind == "proposal":
        model = ItineraryProposal
        data = current.content.proposal(1).model_dump(mode="json")
    else:
        model = PlanPatch
        data = {
            "base_version": 1,
            "expected_revision": 1,
            "hotel_evidence_id": None,
        }
    data["hotel_stays"] = [stay]
    data["hotel_evidence_id"] = None
    parsed = model.model_validate(data, context={"persisted": True})
    assert parsed.model_dump(mode="json")["hotel_stays"] == [stay]
    with pytest.raises(ValueError):
        model.model_validate(data)


def test_compatibility_reads_long_content_without_expanding_the_write_limit() -> None:
    """R07：未来30项payload回退可读，旧proposal写入仍不超过24项。"""
    template = saved().content.items[0]
    items = [
        template.model_copy(update={"item_id": uuid4()}).model_dump(mode="json") for _ in range(30)
    ]
    content = PlanContent.model_validate({"items": items}, context={"persisted": True})
    assert len(content.items) == 30
    proposal = {
        "expected_revision": 1,
        "items": [entry.model_dump(mode="json") for entry in (i.proposed() for i in content.items)],
    }
    assert len(ItineraryProposal.model_validate(proposal, context={"persisted": True}).items) == 30
    with pytest.raises(ValueError):
        ItineraryProposal.model_validate(proposal)


@pytest.mark.parametrize("new_field", ["segments", "lodging_budget_unlimited"])
def test_request_input_rejects_single_city_segments_and_non_boolean_unlimited(
    new_field: str,
) -> None:
    """R04：T1.1启用写入后，仍拒绝单段与非严格布尔值，不放宽结构边界。"""
    value: object = (
        [{"city": "京都", "arrive": "2026-11-03", "depart": "2026-11-05"}]
        if new_field == "segments"
        else "true"
    )
    with pytest.raises(ValueError):
        RequestPatch.model_validate({"expected_revision": 0, "set": {new_field: value}})


def test_compatibility_tool_schemas_keep_the_previous_write_fields() -> None:
    """R07：兼容读字段不应向模型工具声明为可写参数。"""
    schemas = {
        definition.name: cast(dict[str, Any], definition.schema) for definition in DEFINITIONS
    }
    proposal_fields = {"expected_revision", "items", "hotel_evidence_id"}
    patch_fields = {"base_version", "expected_revision", "operations", "hotel_evidence_id"}
    assert set(schemas["validate_itinerary"]["properties"]) == proposal_fields
    definitions = schemas["stage_plan_change"]["$defs"]
    assert set(definitions["ItineraryProposal"]["properties"]) == proposal_fields
    assert set(definitions["PlanPatch"]["properties"]) == patch_fields
    assert definitions["ItineraryProposal"]["properties"]["items"]["maxItems"] == 24
    assert definitions["PlanPatch"]["properties"]["operations"]["maxItems"] == 24


def test_compatibility_patch_cannot_expand_legacy_plan_past_24_items() -> None:
    """R07：放宽读取不能改变旧patch合并结果的24项写入边界。"""
    current = saved()
    template = current.content.items[0]
    content = current.content.model_copy(
        update={"items": tuple(template.model_copy(update={"item_id": uuid4()}) for _ in range(24))}
    )
    current = current.model_copy(update={"content": content})
    change = patch(current, [{"op": "add", "item": template.proposed().model_dump(mode="json")}])
    with pytest.raises(ValueError):
        apply_plan_patch(current, change)
    assert len(current.content.items) == 24


def saved() -> SavedPlan:
    evidence = record(place())
    proposal = ItineraryProposal(
        expected_revision=1,
        items=(item(evidence), item(evidence, "2026-11-04T14:00+09:00", "2026-11-04T15:00+09:00")),
        hotel_evidence_id=uuid4(),
    )
    return SavedPlan(
        plan_id=uuid4(),
        version=1,
        request_revision=1,
        content=initial_content(proposal),
        validation=ValidationReport(
            status="partial", checks=(), known_cost=Decimal(0), estimated_cost=Decimal(0)
        ),
        saved_at=datetime.now(UTC),
    )


def patch(current: SavedPlan, operations: list[dict[str, object]]) -> PlanPatch:
    return PlanPatch.model_validate(
        {
            "base_version": current.version,
            "expected_revision": current.request_revision,
            "operations": operations,
        }
    )


def test_local_update_keeps_other_day_and_same_place_distinct() -> None:
    current = saved()
    first, second = current.content.items
    assert first.place_evidence_id == second.place_evidence_id and first.item_id != second.item_id
    replacement = second.proposed().model_dump(mode="json") | {
        "start": "2026-11-04T15:00+09:00",
        "end": "2026-11-04T16:00+09:00",
    }
    content = apply_plan_patch(
        current,
        patch(current, [{"op": "update", "item_id": str(second.item_id), "item": replacement}]),
    )
    assert content.items[0] == first and content.items[1].item_id == second.item_id
    assert content.hotel_evidence_id == current.content.hotel_evidence_id
    changes = differences(current.content, content)
    assert len(changes) == 1 and changes[0].item_id == second.item_id and changes[0].op == "update"


def test_add_and_remove_assign_id_and_preserve_remaining_items() -> None:
    current = saved()
    first, second = current.content.items
    content = apply_plan_patch(
        current,
        patch(
            current,
            [
                {"op": "remove", "item_id": str(second.item_id)},
                {
                    "op": "add",
                    "after_item_id": str(first.item_id),
                    "item": second.proposed().model_dump(mode="json"),
                },
            ],
        ),
    )
    assert content.items[0] == first and content.items[1].item_id not in {
        first.item_id,
        second.item_id,
    }
    assert {change.op for change in differences(current.content, content)} == {"add", "remove"}
    clear = PlanPatch.model_validate(
        {"base_version": 1, "expected_revision": 1, "hotel_evidence_id": None}
    )
    assert apply_plan_patch(current, clear).hotel_evidence_id is None


@pytest.mark.parametrize("fault", ["locked", "missing", "anchor", "version"])
def test_invalid_patch_cannot_change_current_plan(fault: str) -> None:
    current = saved()
    first = current.content.items[0]
    operations: list[dict[str, object]] = [{"op": "remove", "item_id": str(first.item_id)}]
    if fault == "locked":
        current = current.model_copy(
            update={
                "content": current.content.model_copy(
                    update={
                        "items": (
                            first.model_copy(update={"locked": True}),
                            current.content.items[1],
                        )
                    }
                )
            }
        )
    if fault == "missing":
        operations[0]["item_id"] = str(uuid4())
    if fault == "anchor":
        operations = [
            {
                "op": "add",
                "after_item_id": str(uuid4()),
                "item": first.proposed().model_dump(mode="json"),
            }
        ]
    change = patch(current, operations)
    if fault == "version":
        change = change.model_copy(update={"base_version": 2})
    before = current.model_dump(mode="json")
    with pytest.raises(ValueError):
        apply_plan_patch(current, change)
    assert current.model_dump(mode="json") == before


def test_duplicate_operations_ids_or_all_items_removed_fail() -> None:
    current = saved()
    first = current.content.items[0]
    with pytest.raises(ValidationError, match="修改一次"):
        patch(current, [{"op": "remove", "item_id": str(first.item_id)}] * 2)
    with pytest.raises(ValidationError, match="不能重复"):
        PlanContent(items=(first, first))
    with pytest.raises(ValidationError):
        apply_plan_patch(
            current,
            patch(
                current,
                [{"op": "remove", "item_id": str(item.item_id)} for item in current.content.items],
            ),
        )
    with pytest.raises(ValidationError, match="需要明确"):
        patch(current, [])
