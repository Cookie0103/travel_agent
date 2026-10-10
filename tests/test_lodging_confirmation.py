"""R13：行程住宿预算的未答/金额/不限三态与有限离线追问。"""

from datetime import date

import pytest

from backend.agent.fixture_conditions import fixture_patch, missing_question
from backend.domain.conversation import ConversationState, Task, conversation_view, task_missing
from backend.domain.travel_request import (
    ConversationRequestPatch,
    TravelRequest,
    apply_request_patch,
)
from tests.test_itinerary import request


def ready_request() -> TravelRequest:
    return request().model_copy(
        update={
            "soft_constraints": ("节奏：标准",),
            "hard_constraints": ("住宿：无要求", "房型：无要求", "床型：无要求"),
        }
    )


def test_overnight_itinerary_requires_only_nightly_budget_and_accepts_awaiting_field() -> None:
    """R13：不从全程金额推住宿预算，不新增全程预算/币种追问。"""
    current = ready_request()
    assert task_missing(current, "itinerary") == ("lodging_budget",)
    state = ConversationState.model_validate(
        {"pending_tasks": ["itinerary"], "awaiting_field": "lodging_budget"}
    )
    view = conversation_view(state, current)
    assert view["missing_fields"] == ["lodging_budget"] and view["ready_tasks"] == []
    assert view["awaiting_field"] == "lodging_budget"


@pytest.mark.parametrize("choice", ["unlimited", "amount", "zero_nights", "hotel_comparison"])
def test_resolved_or_inapplicable_lodging_budget_does_not_block(choice: str) -> None:
    """R13：已回答、当日往返与单独酒店比较都不重复追問住宿金额。"""
    current = ready_request()
    task: Task = "hotel_comparison" if choice == "hotel_comparison" else "itinerary"
    if choice == "unlimited":
        current = current.model_copy(update={"lodging_budget_unlimited": True})
    elif choice == "amount":
        current = TravelRequest.model_validate(
            {
                **current.model_dump(),
                "lodging_budget": {
                    "amount": {"upper": "8000"},
                    "basis": "per_room_night",
                    "currency": "JPY",
                },
            }
        )
    elif choice == "zero_nights":
        current = current.model_copy(update={"end_date": current.start_date})
    assert "lodging_budget" not in task_missing(current, task)


def test_fixture_asks_budget_once_and_unlimited_answer_resolves_it() -> None:
    """R13：仅问每间每晚；当前预算短答不限写三态，继续不问金额或币种。"""
    current = ready_request()
    question = missing_question(current, task="itinerary")
    assert "每间房每晚" in question and "不限" in question
    assert "全程预算" not in question and "币种" not in question
    patch = fixture_patch("不限", current, date(2026, 10, 10), awaiting_field="lodging_budget")
    updated, _ = apply_request_patch(current, ConversationRequestPatch.model_validate(patch))
    assert updated.lodging_budget_unlimited and updated.lodging_budget is None
    assert "lodging_budget" not in task_missing(updated, "itinerary")
    assert "每间房每晚" not in missing_question(updated, task="itinerary")


def test_unscoped_unlimited_does_not_guess_which_condition_to_clear() -> None:
    """R13：没有当前预算问题，裸不限不能放宽其他已知事实。"""
    patch = fixture_patch("不限", ready_request(), date(2026, 10, 10))
    assert patch["set"] == {} and patch["clear"] == []


def test_explicit_nightly_amount_replaces_unlimited_without_guessing_trip_budget() -> None:
    """R13：明确金额为JPY每房每晚，清除互斥不限，保留全程预算。"""
    current = ready_request().model_copy(update={"lodging_budget_unlimited": True})
    patch = fixture_patch("住宿每晚8000", current, date(2026, 10, 10))
    updated, _ = apply_request_patch(current, ConversationRequestPatch.model_validate(patch))
    assert updated.lodging_budget and updated.lodging_budget.amount.upper == 8000
    assert updated.lodging_budget.basis == "per_room_night"
    assert updated.lodging_budget.currency == "JPY" and not updated.lodging_budget_unlimited
    assert updated.budget == current.budget


def test_contradictory_amount_and_unlimited_does_not_record_either_choice() -> None:
    """R13：同句互斥回答仍澄清，不任选一个或丢掉金额。"""
    patch = fixture_patch("住宿每晚8000，住宿预算不限", ready_request(), date(2026, 10, 10))
    assert patch["set"] == {} and patch["clear"] == []


@pytest.mark.parametrize("answer", ["8000日元", "住宿每间房每晚8000日元"])
def test_nightly_question_accepts_an_explicit_amount_in_the_requested_basis(answer: str) -> None:
    """R13：当前每晚问题的金额短答按请求口径写入，不误当全程金额。"""
    current = ready_request()
    patch = fixture_patch(answer, current, date(2026, 10, 10), awaiting_field="lodging_budget")
    updated, _ = apply_request_patch(current, ConversationRequestPatch.model_validate(patch))
    assert updated.lodging_budget and updated.lodging_budget.amount.upper == 8000
    assert updated.lodging_budget.basis == "per_room_night"
    assert updated.budget == current.budget


def test_clearing_an_unlimited_answer_returns_budget_to_unanswered() -> None:
    """R13：清空住宿预算也清除不限，三态回到未回答，允许重新确认。"""
    current = ready_request().model_copy(update={"lodging_budget_unlimited": True})
    patch = fixture_patch("清空住宿预算", current, date(2026, 10, 10))
    updated, _ = apply_request_patch(current, ConversationRequestPatch.model_validate(patch))
    assert not updated.lodging_budget_unlimited and updated.lodging_budget is None
    assert "lodging_budget" in task_missing(updated, "itinerary")


def test_answering_current_budget_question_is_an_explicit_value_for_source_guard() -> None:
    """R13：当前问题的明确短答可替换手填false，不绕过其他字段来源守卫。"""
    patch = fixture_patch(
        "不限", ready_request(), date(2026, 10, 10), awaiting_field="lodging_budget"
    )
    assert patch["explicit_fields"] == ["lodging_budget_unlimited"]


@pytest.mark.parametrize("old_unlimited", [False, True])
@pytest.mark.parametrize("choice", ["住宿预算不限", "住宿每晚8000"])
def test_setting_and_clearing_budget_in_one_sentence_requires_clarification(
    old_unlimited: bool, choice: str
) -> None:
    """R13：赋值与清空矛盾不依赖旧三态，也不能任选最后一个指令。"""
    current = ready_request().model_copy(update={"lodging_budget_unlimited": old_unlimited})
    patch = fixture_patch(choice + "，清空住宿预算", current, date(2026, 10, 10))
    assert patch["set"] == {} and patch["clear"] == []
