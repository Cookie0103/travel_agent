"""F2：只凭实际事件否定虚构卡片/重试/过期说法，资料不足保留未知。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.external_data import ExternalAttempt
from eval.claims import claim_consistency


@pytest.mark.parametrize(
    "answer", ["也可以点页面上的预算确认卡选择继续或保持原预算。", "适配器自动重试一次后仍未成功。"]
)
def test_actual_failed_samples_cannot_claim_a_card_or_retry(answer: str) -> None:
    context = RunContext(uuid4())
    events = (
        RuntimeEvent(
            context,
            "tool_finished",
            tool_name="search_hotel_offers",
            code="validation",
            external=ExternalAttempt(kind="bad_request", status=400, attempts=1),
        ),
    )
    assert claim_consistency(answer, events)["passed"] is False


@pytest.mark.parametrize(
    "answer",
    [
        "没有触发预算放宽，也没有改动你的预算。",
        "未出现预算确认卡，所以没有接受的选项可点。",
        "查询失败，没有自动重试。",
        "若以后有合适方案，再给你预算确认卡。",
    ],
)
def test_negative_or_future_explanations_do_not_claim_a_current_card(answer: str) -> None:
    assert claim_consistency(answer, ())["passed"] is True


def test_card_and_retry_supported_by_the_same_run_pass() -> None:
    context = RunContext(uuid4())
    events = (
        RuntimeEvent(
            context,
            "presentation",
            presentation={"data": {"component": "choice", "kind": "budget_relaxation"}},
        ),
        RuntimeEvent(
            context,
            "tool_finished",
            tool_name="search_hotel_offers",
            external=ExternalAttempt(attempts=2, recovered_from="rate_limited"),
        ),
    )
    assert claim_consistency("页面上的预算确认卡已展示；已自动重试一次。", events)["passed"] is True


def test_expired_claim_requires_actual_quote_time() -> None:
    now = datetime.now(UTC)
    assert (
        claim_consistency(
            "报价已过期", (), answered_at=now, valid_until=(now + timedelta(minutes=5),)
        )["passed"]
        is False
    )
    assert (
        claim_consistency(
            "报价已过期", (), answered_at=now, valid_until=(now - timedelta(seconds=1),)
        )["passed"]
        is True
    )
    assert claim_consistency("报价已过期", ())["expiry"] is None


@pytest.mark.parametrize(
    "answer",
    [
        "已尝试的步骤：按价格重新查询、筛选三档。",
        "已尝试按价格重新查询。",
        "不用再点预算确认卡。",
        "不需要预算确认卡。",
        "不要点预算确认卡。",
        "不必点预算确认卡。",
    ],
)
def test_step_descriptions_and_negative_instructions_are_not_claims(answer: str) -> None:
    context = RunContext(uuid4())
    events = (
        RuntimeEvent(
            context,
            "tool_finished",
            tool_name="search_hotel_offers",
            external=ExternalAttempt(attempts=2),
        ),
    )
    assert claim_consistency(answer, events)["passed"] is True


def test_unrelated_negative_clause_does_not_hide_a_fabricated_card() -> None:
    assert (
        claim_consistency("没有预算内方案，但预算确认卡已生成，请点击接受。", ())["passed"] is False
    )
    assert claim_consistency("上轮的预算确认卡已经回答。", ())["card"] is None


def test_card_kind_follows_the_actual_card_word_not_unrelated_budget_text() -> None:
    context = RunContext(uuid4())
    events = (
        RuntimeEvent(
            context,
            "presentation",
            presentation={"data": {"component": "choice", "kind": "memory_confirm"}},
        ),
    )
    assert claim_consistency("预算保持原样，只提出记忆确认卡。", events)["passed"] is True


def test_offering_to_show_a_future_card_does_not_assert_it_is_visible() -> None:
    assert claim_consistency("我可以展示节奏选择卡让你选。", ())["passed"] is True
