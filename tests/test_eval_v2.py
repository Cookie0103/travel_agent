"""V2评测设施：连续成功、终态子集、过程恢复和校准均不从模型自述取真值。"""

from uuid import uuid4

import pytest

from backend.domain.execution import RunContext, RuntimeEvent
from backend.domain.external_data import ExternalAttempt
from eval.calibration import agreement
from eval.metrics import constraint_scores, process_metrics, subset_matches
from eval.report import reliability


def test_reliability_three_trials_has_distinct_any_and_all_success() -> None:
    rows = [
        {"case_id": name, "repeat": i + 1, "status": status}
        for name, statuses in {
            "a": ["passed", "passed", "failed"],
            "b": ["passed"] * 3,
            "c": ["failed"] * 3,
        }.items()
        for i, status in enumerate(statuses)
    ]
    result = reliability(rows, 3)
    assert result["pass_at_1"] == pytest.approx(5 / 9)
    assert result["pass_at_k"] == pytest.approx(2 / 3)
    assert result["pass_power_k"] == pytest.approx(1 / 3)
    assert reliability(rows[:-1], 3)["pass_power_k"] is None


def test_state_subset_checks_nested_values_and_exact_list_size() -> None:
    assert subset_matches(
        {"request": {"pace": "标准", "revision": 2}}, {"request": {"pace": "标准"}}
    )
    assert not subset_matches({"hotel_stays": [{"city": "京都"}]}, {"hotel_stays": []})
    assert not subset_matches({"budget": 20000}, {"budget": 30000})


def test_process_metrics_only_counts_observed_recovery_and_user_error_cards() -> None:
    context = RunContext(uuid4())
    call = uuid4()
    events = (
        RuntimeEvent(context, "tool_started", tool_name="search_hotel_offers", tool_call_id=call),
        RuntimeEvent(
            context,
            "tool_finished",
            tool_name="search_hotel_offers",
            tool_call_id=call,
            external=ExternalAttempt(attempts=2, recovered_from="rate_limited"),
        ),
    )
    result = process_metrics(events, "", ())
    assert result["recovered_without_user"] == 1
    assert result["user_visible_first_errors"] == 0
    assert result["duplicate_calls"] is None
    assert (
        process_metrics((), "offer_id=00000000-0000-0000-0000-000000000001", ())["grounded_ids"]
        is False
    )


def test_cohens_kappa_is_pending_without_actual_human_labels() -> None:
    assert agreement([])["kappa"] is None
    result = agreement([(1, 1), (1, 0), (0, 0), (0, 1)])
    assert result["exact_rate"] == 0.5 and result["kappa"] == 0
    assert result["confusion"] == [[1, 1], [1, 1]]


@pytest.mark.parametrize("skipped", [False, True])
def test_first_transient_error_card_is_counted_unless_retry_cannot_fit(skipped: bool) -> None:
    context = RunContext(uuid4())
    info = ExternalAttempt(
        kind="timeout", attempts=1, retry_skipped="deadline" if skipped else None
    )
    event = RuntimeEvent(
        context,
        "presentation",
        presentation={"status": "error", "external": info.model_dump(mode="json")},
    )
    assert process_metrics((event,), "")["user_visible_first_errors"] == (0 if skipped else 1)


@pytest.mark.parametrize("fault", ["closed", "duplicate", "overlap", "wrong_city", "over_budget"])
def test_constraint_grader_rejects_five_bad_saved_candidates(fault: str) -> None:
    from decimal import Decimal

    from backend.domain.evidence import EvidenceRecord
    from backend.domain.plans import PlanContent, PlanItem
    from tests.test_itinerary import NOW, item, place, record, request

    current = request()
    destination = place()
    if fault == "wrong_city":
        destination = destination.model_copy(update={"city": "大阪"})
    evidence = record(destination, current)
    records: tuple[EvidenceRecord, ...] = (evidence,)
    hotel_id = None
    items = [item(evidence)]
    if fault == "closed":
        items = [item(evidence, "2026-11-03T18:00+09:00", "2026-11-03T19:00+09:00")]
    elif fault == "duplicate":
        items.append(item(evidence, "2026-11-03T12:00+09:00", "2026-11-03T13:00+09:00"))
    elif fault == "overlap":
        items.append(item(evidence, "2026-11-03T10:30+09:00", "2026-11-03T11:30+09:00"))
    elif fault == "over_budget":
        from backend.domain.hotels import quote
        from backend.providers.hotel_fixture import load_rates

        current = current.model_copy(update={"budget": Decimal(1)})
        rates, _ = load_rates()
        offer = quote(rates[0], current, NOW)
        assert offer is not None
        hotel = record(offer, current)
        records = (evidence, hotel)
        hotel_id = hotel.evidence_id
    content = PlanContent(
        items=tuple(PlanItem(**visit.model_dump()) for visit in items), hotel_evidence_id=hotel_id
    )
    result = constraint_scores(current, content, records, NOW)
    assert result["all_constraints"] is False
    conflicts = result["conflict_count"]
    assert isinstance(conflicts, int) and conflicts > 0
