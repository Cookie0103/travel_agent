"""F5：回忆否定只作用于目标；保存天数和拒绝后重新出卡不能漏检。"""

from datetime import datetime
from uuid import uuid4

import pytest

from backend.domain.plans import SavedPlan
from eval.simulator import UserAction, recalled
from eval.simulator_metrics import no_reoffer_after_decline, saved_items_cover_segments


def test_simulator_can_submit_form_answers_but_cannot_attach_them_to_other_actions() -> None:
    payload = {
        "kind": "choice",
        "text": "一起确认",
        "choice_id": str(uuid4()),
        "option_id": "confirm",
        "answers": {"transport": ["transit"], "pace": ["standard"], "times": ["yes"]},
    }
    action = UserAction.model_validate(payload)
    assert action.answers == {
        "transport": ("transit",),
        "pace": ("standard",),
        "times": ("yes",),
    }
    with pytest.raises(ValueError):
        UserAction.model_validate(
            {"kind": "message", "text": "继续", "answers": payload["answers"]}
        )


@pytest.mark.parametrize(
    ("answer", "long_term", "expected"),
    [
        ("我知道的：你的长期偏好里记录的是特种兵。还没有你这次的旅行条件。", True, True),
        ("我没有你的节奏记录。", True, False),
        ("你不喜欢特种兵。", True, False),
        ("你没有特种兵节奏的记录。", True, False),
        ("你没有说过特种兵。", True, False),
        ("你的特种兵偏好尚未确认。", True, False),
        ("你已确认特种兵，预算没有提供。", True, True),
        ("没有酒店，但我知道你通常一个人出行。", False, False),
        ("目前不知道你的长期同行偏好。酒店没有结果。", False, True),
        ("没有酒店结果。", False, False),
    ],
)
def test_recall_checks_the_target_clause(answer: str, long_term: bool, expected: bool) -> None:
    assert recalled(answer, long_term=long_term) is expected


SEGMENTS = [
    {"city": city, "arrive": f"2026-11-0{day}", "depart": f"2026-11-0{day + 1}"}
    for city, day in zip(("京都", "大阪", "奈良"), (3, 4, 5), strict=True)
]


def saved(days: tuple[int, ...]) -> SavedPlan:
    return SavedPlan.model_validate(
        {
            "plan_id": uuid4(),
            "version": 1,
            "request_revision": 1,
            "saved_at": datetime.fromisoformat("2026-11-03T09:00:00+09:00"),
            "content": {
                "items": [
                    {
                        "place_evidence_id": uuid4(),
                        "start": f"2026-11-0{d}T09:00:00+09:00",
                        "end": f"2026-11-0{d}T10:00:00+09:00",
                    }
                    for d in days
                ],
                "hotel_stays": [
                    {
                        "check_in": s["arrive"],
                        "check_out": s["depart"],
                        "hotel_evidence_id": uuid4(),
                    }
                    for s in SEGMENTS
                ],
            },
            "validation": {
                "status": "partial",
                "checks": [],
                "known_cost": "0",
                "estimated_cost": "0",
            },
        }
    )


def test_three_hotels_with_only_one_day_is_not_a_complete_saved_itinerary() -> None:
    assert not saved_items_cover_segments(saved((3,)), {"segments": SEGMENTS})
    assert not saved_items_cover_segments(saved((3, 4, 5)), {"segments": SEGMENTS})
    assert saved_items_cover_segments(saved((3, 4, 5, 6)), {"segments": SEGMENTS})
    assert not saved_items_cover_segments(None, {"segments": SEGMENTS})


def card(
    card_id: str, amount: int = 20000, revision: int = 1, answered: str | None = None
) -> dict[str, object]:
    return {
        "presentation": {
            "data": {
                "component": "choice",
                "kind": "budget_relaxation",
                "session_id": "session-a",
                "expected_revision": revision,
                "choice_id": card_id,
                "answered_option_id": answered,
                "options": [{"option_id": "accept", "label": f"接受每间每晚¥{amount}（全程共用）"}],
            }
        }
    }


@pytest.mark.parametrize(
    ("amount", "revision", "expected"), [(20000, 1, False), (30000, 1, True), (20000, 2, True)]
)
def test_reoffer_checks_same_amount_and_revision(
    amount: int, revision: int, expected: bool
) -> None:
    dialogue = [
        {"user": {"kind": "message"}, "presentations": [card("first")]},
        {
            "user": {"kind": "choice", "choice_id": "first", "option_id": "keep"},
            "presentations": [card("next", amount, revision)],
        },
    ]
    assert no_reoffer_after_decline(dialogue) is expected


def test_answered_historical_card_is_not_a_reoffer_and_missing_source_is_unknown() -> None:
    assert (
        no_reoffer_after_decline(
            [
                {"user": {}, "presentations": [card("first")]},
                {
                    "user": {"kind": "choice", "choice_id": "first", "option_id": "keep"},
                    "presentations": [card("first", answered="keep")],
                },
            ]
        )
        is True
    )
    assert (
        no_reoffer_after_decline(
            [
                {
                    "user": {"kind": "choice", "choice_id": "missing", "option_id": "keep"},
                    "presentations": [],
                }
            ]
        )
        is None
    )
