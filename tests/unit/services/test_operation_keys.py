"""R12规范参数：默认字段等价，真实set/clear和酒店保留/清空不能合并。"""

from uuid import uuid4

from backend.domain.plans import StageInput
from backend.domain.travel_request import RequestPatch
from backend.persistence.operations import key


def test_request_default_clear_equivalent_but_explicit_updates_are_distinct() -> None:
    one = RequestPatch.model_validate({"expected_revision": 1, "set": {"rooms": 2}})
    two = RequestPatch.model_validate({"expected_revision": 1, "set": {"rooms": 2}, "clear": []})
    assert key(one) == key(two)
    assert key(
        RequestPatch.model_validate(
            {"expected_revision": 1, "set": {"budget": "100"}, "clear": ["rooms", "adults"]}
        )
    ) == key(
        RequestPatch.model_validate(
            {"expected_revision": 1, "set": {"budget": "100.00"}, "clear": ["adults", "rooms"]}
        )
    )
    assert key(one) != key(
        RequestPatch.model_validate({"expected_revision": 1, "clear": ["rooms"]})
    )
    assert key(RequestPatch(expected_revision=1)) != key(
        RequestPatch.model_validate({"expected_revision": 1, "set": {"timezone": "Asia/Tokyo"}})
    )


def test_plan_patch_hotel_absent_and_explicit_null_remain_different() -> None:
    remove = {"op": "remove", "item_id": str(uuid4())}
    patch: dict[str, object] = {"base_version": 1, "expected_revision": 1, "operations": [remove]}
    body = {
        "change": {
            "kind": "patch",
            "plan_id": str(uuid4()),
            "patch": patch,
        }
    }
    keep = StageInput.model_validate(body)
    patch["hotel_evidence_id"] = None
    clear = StageInput.model_validate(body)
    assert key(keep) != key(clear)
