from backend.domain.hotels import PARTNER_LABEL
from eval.commerce.parameters import load_parameters
from eval.commerce.score import rescore
from eval.commerce.trials import evaluate, market
from eval.v3.report import commerce_summary


def test_trial_sheet_uses_displayed_hotel_and_failed_run_is_zero() -> None:
    identity, (hotel, _, _) = next(
        (key, entry) for key, entry in market().items() if not entry[2].partner
    )
    request = {
        "city": hotel.city,
        "start_date": "2026-11-01",
        "end_date": "2026-11-03",
        "rooms": 1,
        "adults": 2,
        "child_ages": [],
        "currency": "JPY",
    }
    original = {
        "hotel_id": identity,
        "stay": request,
        "partner": False,
        "partner_label": None,
        "currency": "JPY",
        "total": "24000",
        "review_average": 4,
        "review_count": 44,
        "breakfast": True,
    }
    presentations = [{"turn": 3, "cards": [original]}]
    params = load_parameters()
    older = [
        {"turn": 1, "cards": [{**original, "stay": {**request, "end_date": "2026-11-04"}}]},
        {"turn": 2, "cards": [{**original, "stay": {**request, "adults": 1}}]},
    ]
    good = evaluate([*older, *presentations], request, params)
    assert [group["turn"] for group in good["groups"]] == [3]
    rejected = evaluate(presentations, request, params, ("draft_conflict",))
    assert good["passed"] and good["total_jpy"] > 0 and rescore(good, params) == good["total_jpy"]
    assert not rejected["passed"] and rejected["total_jpy"] == 0 and not rejected["groups"]
    summary = commerce_summary([{"commerce": good}, {"commerce": rejected}])
    assert summary and summary["rule_pass_rate"] == 0.5
    assert summary["expected_score_jpy"] == good["total_jpy"] / 2
    original["partner_label"] = PARTNER_LABEL
    assert evaluate(presentations, request, params)["violations"] == ["partner_disclosure"]
