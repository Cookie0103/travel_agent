"""逐项手算商业期望分的最小验收。"""

from math import log

import pytest

from eval.commerce.parameters import Prior, Registry, load_parameters
from eval.commerce.score import Candidate, score


def setup(**weights: float) -> Registry:
    params = load_parameters()
    empty = Prior(value=0, bounds=(0, 0), source="手算例", unit="测试")
    priors = {
        key: prior.model_copy(update={"value": weights[key]}) if key in weights else empty
        for key, prior in params.priors.items()
    }
    policy = params.policy.model_copy(
        update={"max_partner_share": 1.0, "min_partner_relevance": 0.0, "partner_value": 0.0}
    )
    return params.model_copy(update={"priors": priors, "policy": policy})


def hotel(
    identity: str, *, price: float = 100, rating: float = 0, partner: bool = False
) -> Candidate:
    return Candidate(
        id=identity,
        price_jpy=price,
        rating=rating,
        reviews=1,
        station_minutes=0,
        breakfast=False,
        partner=partner,
        commission=0.1,
    )


def test_outside_option_absorbs_probability_when_there_is_nothing_to_book() -> None:
    result = score([], 100, "general", setup())
    assert (result.no_booking, result.booking_probability, result.total_jpy) == (1, 0, 0)


def test_equal_utilities_split_probability_and_each_expected_yen() -> None:
    result = score([hotel("A"), hotel("B", price=200)], 100, "general", setup())
    assert result.no_booking == pytest.approx(1 / 3)
    assert [entry.expected_jpy for entry in result.hotels] == pytest.approx([10 / 3, 20 / 3])
    assert result.total_jpy == pytest.approx(10)


def test_rating_and_price_contributions_reconstruct_attraction() -> None:
    params = setup(rating=log(2), price_ratio=-log(2))
    result = score([hotel("A", rating=2)], 100, "general", params)
    row = result.hotels[0]
    assert row.attraction == pytest.approx(log(2))
    assert sum(value.total for value in row.components.values()) == pytest.approx(log(2))
    assert row.probability == pytest.approx(2 / 3)
    assert result.total_jpy == pytest.approx(20 / 3)


def test_one_worse_partner_ahead_of_one_better_hotel_halves_value() -> None:
    params = setup(rating=log(2))
    a, b = hotel("A", partner=True), hotel("B", rating=1)
    result = score([a, b], 100, "general", params)
    assert result.inversions == (("A", "B"),)
    assert result.comparable_pairs == 1
    assert result.trust_discount == 0.5
    assert result.total_jpy == pytest.approx(3.75)
    assert score([b, a], 100, "general", params).total_jpy == pytest.approx(7.5)


def test_rule_and_partner_policy_failures_score_zero() -> None:
    params = setup()
    a = hotel("A", partner=True)
    result = score([a], 100, "general", params, rule_violations=("trip_dates",))
    assert result.violations == ("trip_dates",) and result.total_jpy == 0
    assert not result.hotels
    params = params.model_copy(
        update={"policy": params.policy.model_copy(update={"max_partner_share": 0.5})}
    )
    result = score([a], 100, "general", params)
    assert not result.passed and result.total_jpy == 0
    assert result.violations == ("partner_share",)
