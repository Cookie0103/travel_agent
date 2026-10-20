"""claims-v6：服务端事实参与的三类声明；不传facts时输出与旧版一致。"""

import pytest

from eval.claims import CLAIM_SCORER_VERSION, ClaimFacts, claim_consistency


def test_version_bumped() -> None:
    assert CLAIM_SCORER_VERSION == "claims-v6-facts"


def test_without_facts_output_has_only_legacy_keys() -> None:
    result = claim_consistency("已为你记住慢节奏，酒店也在预算内。", ())
    assert result == {"card": True, "retry": True, "expiry": True, "passed": True}


@pytest.mark.parametrize(
    ("answer", "facts", "key"),
    [
        ("这些酒店都在预算内。", ClaimFacts(within_budget_cards=False), "budget"),
        ("没有超预算。", ClaimFacts(within_budget_cards=False), "budget"),
        ("酒店已选定，接着排行程。", ClaimFacts(hotel_selected=False), "hotel_selected"),
        ("已为你记住这个偏好。", ClaimFacts(memory_active=False), "remembered"),
    ],
)
def test_false_assertions_are_flagged(answer: str, facts: ClaimFacts, key: str) -> None:
    result = claim_consistency(answer, (), facts=facts)
    assert result[key] is False and result[key + "_claimed"] is True
    assert result["passed"] is False


@pytest.mark.parametrize(
    ("answer", "facts", "key"),
    [
        ("这些酒店都在预算内。", ClaimFacts(within_budget_cards=True), "budget"),
        ("酒店已选定。", ClaimFacts(hotel_selected=True), "hotel_selected"),
        ("已为你记住这个偏好。", ClaimFacts(memory_active=True), "remembered"),
    ],
)
def test_true_assertions_pass(answer: str, facts: ClaimFacts, key: str) -> None:
    result = claim_consistency(answer, (), facts=facts)
    assert result[key] is True and result[key + "_claimed"] is True and result["passed"] is True


@pytest.mark.parametrize(
    "answer",
    [
        "还没有记住任何偏好。",
        "若以后有合适方案，再告诉你已记住。",
        "未选定酒店。",
        "不会记住这条。",
    ],
)
def test_negated_or_future_statements_are_not_assertions(answer: str) -> None:
    result = claim_consistency(answer, (), facts=ClaimFacts(False, False, False))
    assert result["passed"] is True
    assert not any(
        result[k] for k in ("budget_claimed", "hotel_selected_claimed", "remembered_claimed")
    )


def test_unknown_facts_give_unknown_not_failure() -> None:
    result = claim_consistency("这些酒店都在预算内。", (), facts=ClaimFacts())
    assert result["budget"] is None and result["passed"] is None


@pytest.mark.parametrize(
    ("answer", "key"),
    [
        ("在预算范围内的酒店暂时没有找到。", "budget"),
        ("您可以选择在预算内的方案。", "budget"),
        ("要不要看看在预算内的酒店？", "budget"),
        ("是否需要我挑选在预算内的酒店", "budget"),
        ("符合预算的酒店暂无。", "budget"),
        ("要我帮你选好酒店吗？", "hotel_selected"),
        ("你想让我记住了解你的偏好吗？", "remembered"),
    ],
)
def test_offers_questions_and_absence_are_not_assertions(answer: str, key: str) -> None:
    result = claim_consistency(answer, (), facts=ClaimFacts(False, False, False))
    assert result[key + "_claimed"] is False and result["passed"] is True


def test_asserted_budget_claim_in_one_clause_survives_absence_in_another() -> None:
    result = claim_consistency(
        "这家酒店在预算内，但没有早餐。", (), facts=ClaimFacts(within_budget_cards=False)
    )
    assert result["budget"] is False


def test_already_chose_a_hotel_is_detected() -> None:
    result = claim_consistency("我已经选了京都的酒店。", (), facts=ClaimFacts(hotel_selected=False))
    assert result["hotel_selected"] is False and result["hotel_selected_claimed"] is True
