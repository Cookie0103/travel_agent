"""R07：稳定item_id的局部增改删、锁定和未修改字段保留，不靠地点ID批量改写。"""

from datetime import UTC, datetime
from decimal import Decimal
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
from tests.test_itinerary import item, place, record


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
