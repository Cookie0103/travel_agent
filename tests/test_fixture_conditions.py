"""有限离线表达仅提取明确事实，相对日期可复现，不冒充通用模型。"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.agent.fixture_conditions import fixture_patch
from backend.domain.travel_request import ConversationRequestPatch, TravelRequest


def test_acceptance_sentence_keeps_unknown_fields_and_resolves_calendar_weekend() -> None:
    patch = fixture_patch(
        "下周末两大人一小孩(5岁)去札幌，全程8万", TravelRequest(), date(2026, 10, 8)
    )
    assert patch["set"] == {
        "city": "札幌",
        "adults": 2,
        "child_ages": [5],
        "budget": "80000",
        "start_date": "2026-10-17",
        "end_date": "2026-10-18",
    }
    assert patch["explicit_fields"] == [] and patch["clear"] == []


def test_two_budgets_keep_range_and_room_night_basis_without_guessing_quantities() -> None:
    patch = fixture_patch("去京都，全程6万，酒店每晚2–3万", TravelRequest(), date(2026, 10, 8))
    validated = ConversationRequestPatch.model_validate(patch)
    assert validated.set_fields.budget == 60000
    assert validated.set_fields.lodging_budget
    assert validated.set_fields.lodging_budget.amount.lower == 20000
    assert validated.set_fields.lodging_budget.amount.upper == 30000
    assert validated.set_fields.rooms is None and validated.set_fields.start_date is None


@pytest.mark.parametrize(
    ("prompt", "explicit"),
    [
        ("改成3个大人", ["adults"]),
        ("可能3个大人", []),
        ("如果改成3个大人呢", []),
    ],
)
def test_hypothetical_changes_do_not_claim_explicit_override(
    prompt: str, explicit: list[str]
) -> None:
    assert fixture_patch(prompt, TravelRequest(), date(2026, 10, 8))["explicit_fields"] == explicit


def test_child_count_without_ages_and_unrecognized_prompt_never_fill_defaults() -> None:
    assert fixture_patch("一个小孩", TravelRequest(), date(2026, 10, 8))["set"] == {}
    assert fixture_patch("请帮我计划", TravelRequest(), date(2026, 10, 8))["set"] == {}


def test_clear_only_requested_budget_and_pace_preserves_unrelated_soft_constraints() -> None:
    request = TravelRequest(soft_constraints=("少走路", "标准"))
    patch = fixture_patch("清空全程预算，改成慢节奏", request, date(2026, 10, 8))
    assert patch["clear"] == ["budget"]
    assert patch["set"] == {"soft_constraints": ["少走路", "节奏：慢节奏"]}
    assert patch["explicit_fields"] == ["budget", "soft_constraints"]


def test_tool_explicit_fields_are_subset_and_cannot_forge_source() -> None:
    with pytest.raises(ValidationError):
        ConversationRequestPatch.model_validate(
            {"expected_revision": 0, "explicit_fields": ["adults"]}
        )
    with pytest.raises(ValidationError):
        ConversationRequestPatch.model_validate({"expected_revision": 0, "source": "user_form"})


@pytest.mark.parametrize("prompt", ["如果改成3个大人呢", "不要清空全程预算", "不要改成慢节奏"])
def test_hypotheses_and_negations_do_not_write_or_clear_unknown_or_existing_facts(
    prompt: str,
) -> None:
    patch = fixture_patch(prompt, TravelRequest(budget=Decimal("80000")), date(2026, 10, 8))
    assert patch["set"] == {} and patch["clear"] == [] and patch["explicit_fields"] == []


def test_explicit_pace_change_uses_existing_prefix_and_preserves_unrelated_constraints() -> None:
    request = TravelRequest(soft_constraints=("少走路", "节奏：标准"))
    patch = fixture_patch("改成慢节奏", request, date(2026, 10, 8))
    assert patch["set"] == {"soft_constraints": ["少走路", "节奏：慢节奏"]}


def test_affirmative_tebie_is_not_misread_as_bie_negation() -> None:
    patch = fixture_patch("特别想去札幌", TravelRequest(), date(2026, 10, 8))
    assert patch["set"] == {"city": "札幌"}


def test_explicit_foreign_lodging_currency_is_preserved_without_conversion() -> None:
    patch = fixture_patch("全程5万，酒店每晚2万 EUR", TravelRequest(), date(2026, 10, 8))
    validated = ConversationRequestPatch.model_validate(patch)
    assert validated.set_fields.lodging_budget
    assert validated.set_fields.lodging_budget.currency == "EUR"
    assert validated.set_fields.lodging_budget.amount.lower == 20000


def test_foreign_trip_budget_is_not_silently_saved_as_yen() -> None:
    patch = fixture_patch("全程5万美元", TravelRequest(), date(2026, 10, 8))
    assert patch["set"] == {} and patch["clear"] == []


def test_any_explicit_foreign_trip_budget_in_the_sentence_requires_clarification() -> None:
    patch = fixture_patch("全程5万JPY，总预算8万美元", TravelRequest(), date(2026, 10, 8))
    assert patch["set"] == {} and patch["clear"] == []


def test_other_soft_preferences_do_not_make_unspoken_pace_known() -> None:
    from backend.agent.fixture_conditions import missing_question

    request = TravelRequest.model_validate(
        {
            "city": "京都",
            "start_date": "2026-11-03",
            "end_date": "2026-11-05",
            "adults": 2,
            "child_ages": [],
            "rooms": 1,
            "soft_constraints": ["少走路"],
        }
    )
    assert "节奏" in missing_question(request)
