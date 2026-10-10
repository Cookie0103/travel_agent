"""R07：稳定item_id的局部增改删、锁定和未修改字段保留，不靠地点ID批量改写。"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.domain import plans as plan_models
from backend.domain.hotels import quote
from backend.domain.itinerary import HotelStay, ItineraryProposal, ValidationReport
from backend.domain.plans import (
    PlanContent,
    PlanPatch,
    SavedPlan,
    apply_plan_patch,
    differences,
    initial_content,
)
from backend.domain.travel_request import RequestPatch, TravelRequest
from backend.providers.hotel_fixture import load_rates
from backend.services.plans import LockInput
from backend.tools.contracts import ToolResult
from backend.tools.travel import DEFINITIONS, bounded_plan
from tests.test_itinerary import item, place, record


@pytest.mark.parametrize("kind", ["content", "proposal", "patch"])
def test_stay_collection_and_legacy_hotel_cannot_both_hold_references(kind: str) -> None:
    """R07：旧酒店字段与分段酒店引用互斥，结构错误在模型入界拒绝。"""
    current = saved()
    stay = HotelStay.model_validate(
        {"check_in": "2026-11-03", "check_out": "2026-11-05", "hotel_evidence_id": str(uuid4())}
    )
    models: dict[str, type[PlanContent] | type[ItineraryProposal] | type[PlanPatch]] = {
        "content": PlanContent,
        "proposal": ItineraryProposal,
        "patch": PlanPatch,
    }
    data = (
        current.content.model_dump()
        if kind == "content"
        else current.content.proposal(1).model_dump()
        if kind == "proposal"
        else {"base_version": 1, "expected_revision": 1}
    )
    with pytest.raises(ValidationError):
        models[kind].model_validate({**data, "hotel_evidence_id": uuid4(), "hotel_stays": (stay,)})


def test_default_plan_result_compacts_many_quotes_without_losing_stay_references() -> None:
    """模型读取合法多住宿结果仍受8000字符限制，页面原始报价不被修改。"""
    rates, _ = load_rates()
    start = datetime.fromisoformat("2026-11-03")
    stays = []
    for index in range(6):
        arrival = (start + timedelta(days=index)).date()
        departure = arrival + timedelta(days=1)
        request = TravelRequest(
            revision=1,
            city="京都",
            start_date=arrival,
            end_date=departure,
            adults=2,
            child_ages=(),
            rooms=1,
        )
        offer = quote(rates[0], request, datetime.now(UTC))
        assert offer is not None
        card = offer.card(request)
        card.update(
            hotel_name="合成酒店" * 20,
            address="合成地址" * 100,
            room_type="合成套餐" * 100,
        )
        stays.append(
            {
                "check_in": arrival.isoformat(),
                "check_out": departure.isoformat(),
                "hotel_evidence_id": str(uuid4()),
                "hotel": card,
            }
        )
    data = {"cards": [{"item_id": str(uuid4())}], "hotel_stays": stays}
    original = json.dumps(data, ensure_ascii=False)
    assert len(original) > 8000
    bounded = bounded_plan(ToolResult(data))
    assert len(json.dumps(bounded.payload(), ensure_ascii=False)) <= 8000
    compact = bounded.data["hotel_stays"]
    assert isinstance(compact, list) and len(compact) == 6
    for expected, actual in zip(stays, compact, strict=True):
        assert isinstance(actual, dict)
        for key in ("check_in", "check_out", "hotel_evidence_id"):
            assert actual[key] == expected[key]
    assert json.dumps(data, ensure_ascii=False) == original


def test_stays_of_preserves_legacy_hotel_and_initial_content_keeps_segmented_stays() -> None:
    """R07：旧引用按旅行日期投影；新段引用经过proposal→content不丢失。"""
    current = saved()
    request = TravelRequest.model_validate(
        {"city": "京都", "start_date": "2026-11-03", "end_date": "2026-11-05"}
    )
    legacy_id = uuid4()
    legacy = current.content.model_copy(update={"hotel_evidence_id": legacy_id})
    stays = plan_models.stays_of(legacy, request)
    assert len(stays) == 1 and stays[0].hotel_evidence_id == legacy_id
    assert stays[0].check_in == request.start_date and stays[0].check_out == request.end_date
    proposal = ItineraryProposal(
        expected_revision=1,
        items=tuple(i.proposed() for i in current.content.items),
        hotel_stays=stays,
    )
    content = initial_content(proposal)
    assert content.hotel_stays == stays and content.hotel_evidence_id is None
    assert content.proposal(1).hotel_stays == stays
    assert plan_models.stays_of(content, request) == stays
    assert stays[0].hotel_evidence_id in content.proposal(1).evidence_ids()


def test_stay_patch_replaces_and_clears_the_entire_collection_without_losing_items() -> None:
    """R07：未提供住宿字段保留，显式空列表清除，旧字段可切回单城引用。"""
    current = saved()
    stay = HotelStay.model_validate(
        {"check_in": "2026-11-03", "check_out": "2026-11-05", "hotel_evidence_id": str(uuid4())}
    )
    changed = apply_plan_patch(
        current, PlanPatch(base_version=1, expected_revision=1, hotel_stays=(stay,))
    )
    assert changed.items == current.content.items and changed.hotel_stays == (stay,)
    assert changed.hotel_evidence_id is None
    current = current.model_copy(update={"content": changed})
    unchanged = apply_plan_patch(
        current,
        patch(current, [{"op": "remove", "item_id": str(current.content.items[0].item_id)}]),
    )
    assert unchanged.hotel_stays == (stay,) and unchanged.hotel_evidence_id is None
    replacement = stay.model_copy(update={"hotel_evidence_id": uuid4()})
    replaced = apply_plan_patch(
        current, PlanPatch(base_version=1, expected_revision=1, hotel_stays=(replacement,))
    )
    assert replaced.hotel_stays == (replacement,)
    cleared = apply_plan_patch(
        current, PlanPatch(base_version=1, expected_revision=1, hotel_stays=())
    )
    assert not cleared.hotel_stays and cleared.hotel_evidence_id is None
    old_id = uuid4()
    old = apply_plan_patch(
        current, PlanPatch(base_version=1, expected_revision=1, hotel_evidence_id=old_id)
    )
    assert old.hotel_evidence_id == old_id and not old.hotel_stays


def test_thirty_proposal_items_patch_operations_and_locks_use_the_new_guard() -> None:
    """R07：30项模型入界通过，201项仍拒绝，保留有界防护。"""
    current = saved()
    proposed = current.content.items[0].proposed()
    proposal = ItineraryProposal(expected_revision=1, items=(proposed,) * 30)
    assert len(initial_content(proposal).items) == 30
    operations = [{"op": "add", "item": proposed.model_dump()} for _ in range(30)]
    patch = PlanPatch.model_validate(
        {"base_version": 1, "expected_revision": 1, "operations": operations}
    )
    assert len(apply_plan_patch(current, patch).items) == len(current.content.items) + 30
    locks = LockInput(expected_version=1, locked_item_ids=tuple(uuid4() for _ in range(30)))
    assert len(locks.locked_item_ids) == 30
    with pytest.raises(ValidationError):
        ItineraryProposal(expected_revision=1, items=(proposed,) * 201)
    with pytest.raises(ValidationError):
        PlanPatch.model_validate(
            {"base_version": 1, "expected_revision": 1, "operations": operations * 7}
        )
    with pytest.raises(ValidationError):
        LockInput(expected_version=1, locked_item_ids=tuple(uuid4() for _ in range(201)))


@pytest.mark.parametrize("kind", ["proposal", "patch"])
def test_hotel_stays_round_trip_and_reject_combined_legacy_reference(kind: str) -> None:
    """R07：T1.2启用段引用读写，双引用仍拒绝，不以忽略旧值解决冲突。"""
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
    assert model.model_validate(data).model_dump(mode="json")["hotel_stays"] == [stay]
    data["hotel_evidence_id"] = str(uuid4())
    with pytest.raises(ValueError):
        model.model_validate(data)


def test_long_content_round_trip_keeps_the_new_write_limit_bounded() -> None:
    """R07：T1.2允许30项读写，超过200项的proposal仍拒绝。"""
    template = saved().content.items[0]
    items = [
        template.model_copy(update={"item_id": uuid4()}).model_dump(mode="json") for _ in range(30)
    ]
    content = PlanContent.model_validate({"items": items}, context={"persisted": True})
    assert len(content.items) == 30
    proposed_items = [entry.proposed().model_dump(mode="json") for entry in content.items]
    proposal = {"expected_revision": 1, "items": proposed_items}
    assert len(ItineraryProposal.model_validate(proposal, context={"persisted": True}).items) == 30
    assert len(ItineraryProposal.model_validate(proposal).items) == 30
    proposal["items"] = proposed_items * 7
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


def test_tool_schemas_declare_stays_and_the_shared_item_limit() -> None:
    """R07：工具schema与T1.2模型相同，200项上限不保留隐性24项声明。"""
    schemas = {
        definition.name: cast(dict[str, Any], definition.schema) for definition in DEFINITIONS
    }
    proposal_fields = {"expected_revision", "items", "hotel_evidence_id", "hotel_stays"}
    patch_fields = {
        "base_version",
        "expected_revision",
        "operations",
        "hotel_evidence_id",
        "hotel_stays",
    }
    assert set(schemas["validate_itinerary"]["properties"]) == proposal_fields
    definitions = schemas["stage_plan_change"]["$defs"]
    assert set(definitions["ItineraryProposal"]["properties"]) == proposal_fields
    assert set(definitions["PlanPatch"]["properties"]) == patch_fields
    assert definitions["ItineraryProposal"]["properties"]["items"]["maxItems"] == 200
    assert definitions["PlanPatch"]["properties"]["operations"]["maxItems"] == 200


def test_patch_cannot_expand_plan_past_200_items() -> None:
    """R07：patch合并也受200项保护，拒绝201项而不是只查operations数量。"""
    current = saved()
    template = current.content.items[0]
    content = current.content.model_copy(
        update={
            "items": tuple(template.model_copy(update={"item_id": uuid4()}) for _ in range(200))
        }
    )
    current = current.model_copy(update={"content": content})
    change = patch(current, [{"op": "add", "item": template.proposed().model_dump(mode="json")}])
    with pytest.raises(ValueError):
        apply_plan_patch(current, change)
    assert len(current.content.items) == 200


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
