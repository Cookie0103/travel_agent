"""基于固定参数计算推荐列表的商业期望分，并保留逐项证据。"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from eval.commerce.parameters import Persona, Registry


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    id: str
    price_jpy: float = Field(gt=0)
    rating: float = Field(ge=0, le=5)
    reviews: int = Field(ge=0)
    station_minutes: float = Field(ge=0)
    breakfast: bool
    partner: bool
    commission: float = Field(ge=0, le=1)
    soft_probabilities: Mapping[str, float] = Field(default_factory=dict)


@dataclass(frozen=True)
class Contribution:
    value: float
    weight: float

    @property
    def total(self) -> float:
        return self.value * self.weight


@dataclass(frozen=True)
class HotelScore:
    hotel: Candidate
    rank: int
    components: Mapping[str, Contribution]
    attraction: float
    probability: float
    revenue_jpy: float

    @property
    def expected_jpy(self) -> float:
        return self.probability * self.revenue_jpy


@dataclass(frozen=True)
class Scorecard:
    parameter_version: str
    passed: bool
    violations: tuple[str, ...]
    hotels: tuple[HotelScore, ...]
    no_booking: float
    expected_revenue_jpy: float
    trust_discount: float
    partner_share: float
    inversions: tuple[tuple[str, str], ...]
    comparable_pairs: int
    total_jpy: float

    @property
    def booking_probability(self) -> float:
        return sum(entry.probability for entry in self.hotels)


def _soft_score(hotel: Candidate, params: Registry) -> float:
    result = 0.0
    for name, probability in hotel.soft_probabilities.items():
        if name not in params.soft_items or not 0 <= probability <= 1:
            raise ValueError("软性项未登记或概率超出零到一")
        result += params.soft_items[name].value * probability
    return result


def _components(
    hotel: Candidate, rank: int, budget_jpy: float, weights: Mapping[str, float], params: Registry
) -> dict[str, Contribution]:
    values = {
        "price_ratio": hotel.price_jpy / budget_jpy,
        "rating": hotel.rating,
        "log_reviews": math.log(max(1, hotel.reviews)),
        "station_minutes": hotel.station_minutes,
        "breakfast": float(hotel.breakfast),
        "rank": float(rank - 1),
        "soft": _soft_score(hotel, params),
    }
    return {name: Contribution(value, weights[name]) for name, value in values.items()}


def _probabilities(all_utilities: Sequence[float]) -> tuple[float, ...]:
    if not all(math.isfinite(value) for value in all_utilities):
        raise ValueError("吸引力超出可计算范围")
    origin = max(all_utilities)
    masses = tuple(math.exp(value - origin) for value in all_utilities)
    total = math.fsum(masses)
    return tuple(mass / total for mass in masses)


def score(
    hotels: Sequence[Candidate],
    budget_jpy: float,
    persona: Persona,
    parameters: Registry,
    *,
    rule_violations: tuple[str, ...] = (),
    apply_trust: bool = True,
) -> Scorecard:
    policy = parameters.policy
    if rule_violations:
        return Scorecard(parameters.version, False, rule_violations, (), 1, 0, 1, 0, (), 0, 0)
    if not math.isfinite(budget_jpy) or budget_jpy <= 0:
        raise ValueError("住宿预算必须换算为正的每晚日元额")
    if len({hotel.id for hotel in hotels}) != len(hotels):
        raise ValueError("一个比较列表里同一酒店只应出现一次")

    weights = parameters.weights(persona)
    components = [
        _components(hotel, rank, budget_jpy, weights, parameters)
        for rank, hotel in enumerate(hotels, 1)
    ]
    utilities = [math.fsum(component.total for component in row.values()) for row in components]
    probability = _probabilities((*utilities, parameters.priors["outside"].value))
    relevance = [
        utility - row["rank"].total for utility, row in zip(utilities, components, strict=True)
    ]
    top = hotels[: policy.top_count]
    share = sum(hotel.partner for hotel in top) / len(top) if top else 0.0

    violations = []
    if share > policy.max_partner_share:
        violations.append("partner_share")
    if any(
        hotel.partner and chance < max(probability[:-1], default=0.0) * policy.min_partner_relevance
        for hotel, chance in zip(hotels, probability[:-1], strict=True)
    ):
        violations.append("partner_relevance")

    rows = tuple(
        HotelScore(
            hotel=hotel,
            rank=index + 1,
            components=components[index],
            attraction=utilities[index],
            probability=probability[index],
            revenue_jpy=hotel.price_jpy
            * (hotel.commission + policy.partner_value * hotel.partner * (1 - hotel.commission)),
        )
        for index, hotel in enumerate(hotels)
    )
    inversions = tuple(
        (hotel.id, downstream.id)
        for index, hotel in enumerate(hotels)
        if hotel.partner
        for target, downstream in enumerate(hotels[index + 1 :], index + 1)
        if not downstream.partner and relevance[index] < relevance[target]
    )
    partners = sum(hotel.partner for hotel in hotels)
    pairs = partners * (len(hotels) - partners)
    discount = 1 - policy.gamma * len(inversions) / pairs if pairs and apply_trust else 1.0
    revenue = math.fsum(row.expected_jpy for row in rows)
    return Scorecard(
        parameter_version=parameters.version,
        passed=not violations,
        violations=tuple(violations),
        hotels=rows,
        no_booking=probability[-1],
        expected_revenue_jpy=revenue,
        trust_discount=discount,
        partner_share=share,
        inversions=inversions,
        comparable_pairs=pairs,
        total_jpy=revenue * discount if not violations else 0.0,
    )


def rescore(
    sheet: Mapping[str, Any],
    registry: Registry,
    *,
    apply_trust: bool = True,
    soft: Mapping[str, Mapping[str, float]] | None = None,
) -> float:
    if any(
        code not in {"partner_share", "partner_relevance"} for code in sheet.get("violations", ())
    ):
        return 0.0

    def candidate(raw: dict[str, Any]) -> Candidate:
        values = {
            name: probability
            for name, probability in (soft or {}).get(raw["id"], {}).items()
            if name in registry.soft_items
        }
        return (
            Candidate.model_validate({**raw, "soft_probabilities": values})
            if soft
            else (Candidate.model_validate(raw))
        )

    cards = [
        score(
            [candidate(hotel) for hotel in group["inputs"]],
            group["budget_jpy"],
            group["persona"],
            registry,
            apply_trust=apply_trust,
        )
        for group in sheet["groups"]
    ]
    return (
        math.fsum(card.total_jpy for card in cards) if all(card.passed for card in cards) else 0.0
    )
