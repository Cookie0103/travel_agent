"""根据试验已展示的报价与终态离线计分，保留可重算的分数明细。"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import date
from functools import cache
from typing import Any

from backend.domain.evidence import evidence_conditions
from backend.domain.hotels import PARTNER_LABEL
from backend.domain.travel_request import TravelRequest, city_key, segment_request, trip_segments
from data.eval_world.world import Commission, Hotel, Station, load_world
from eval.commerce.checks import walking_minutes
from eval.commerce.parameters import Registry
from eval.commerce.score import Candidate, score


@cache
def market() -> dict[str, tuple[Hotel, Station, Commission]]:
    world, rates = load_world()
    return {
        str(city_index * 100 + index): (hotel, station, rates[hotel.hotel_id])
        for city_index, station in enumerate(world.stations, 1)
        for index, hotel in enumerate((h for h in world.hotels if h.city == station.city), 1)
    }


def _in_booked_unit(value: float, stay: Mapping[str, Any]) -> float:
    nights = (date.fromisoformat(stay["end_date"]) - date.fromisoformat(stay["start_date"])).days
    rooms = stay["rooms"]
    if nights <= 0 or not isinstance(rooms, int) or rooms < 1:
        raise ValueError("报价缺少有效计价范围")
    return value / (nights * rooms)


def _lodging_budget(request: Mapping[str, Any]) -> float:
    lodging = request.get("lodging_budget")
    if not isinstance(lodging, dict):
        return 15_000.0  # 参数登记表中的基准；用户预算未知或不限时使用
    if lodging["currency"] != "JPY":
        raise ValueError("budget_currency_unverified")
    amount = float(lodging["amount"].get("upper") or lodging["amount"]["lower"])
    return _in_booked_unit(amount, request) if lodging["basis"] == "total" else amount


def _canonical_stay(stay: Mapping[str, Any]) -> dict[str, Any]:
    return {**stay, "city": city_key(stay["city"])}


def _basket(cards: Sequence[Mapping[str, Any]], scope: Mapping[str, Any]) -> tuple[Candidate, ...]:
    candidates: dict[str, Candidate] = {}
    for card in cards:
        hotel, station, commission = market()[str(card["hotel_id"])]
        if commission.partner != bool(card.get("partner")) or commission.partner != (
            card.get("partner_label") == PARTNER_LABEL
        ):
            raise ValueError("partner_disclosure")
        if card["currency"] != "JPY" or card.get("total") is None:
            raise ValueError("price_unverified")
        if (
            card.get("review_average") is None
            or card.get("review_count") is None
            or type(card.get("breakfast")) is not bool
        ):
            raise ValueError("hotel_features_unverified")
        candidates.setdefault(
            hotel.hotel_id,
            Candidate(
                id=hotel.hotel_id,
                price_jpy=_in_booked_unit(float(card["total"]), scope),
                booking_total_jpy=float(card["total"]),
                rating=float(card["review_average"]),
                reviews=int(card["review_count"]),
                station_minutes=walking_minutes(hotel, station),
                breakfast=card["breakfast"],
                partner=commission.partner,
                commission=commission.basis_points / 10_000,
            ),
        )
    return tuple(candidates.values())


def evaluate(
    presentations: Sequence[Mapping[str, Any]],
    request: Mapping[str, Any],
    registry: Registry,
    violations: Sequence[str] = (),
    *,
    apply_trust: bool = True,
) -> dict[str, Any]:
    groups: dict[int, tuple[int | None, list[Mapping[str, Any]]]] = {}
    failures = list(violations)
    if not failures:
        try:
            final = TravelRequest.model_validate(
                {key: value for key, value in request.items() if key in TravelRequest.model_fields}
            )
            stays = [
                _canonical_stay(evidence_conditions(segment_request(final, segment), "hotel_offer"))
                for segment in trip_segments(final)
                if segment.depart > segment.arrive
            ]
            for presentation in presentations:
                current: dict[int, list[Mapping[str, Any]]] = {}
                for card in presentation["cards"]:
                    stay = _canonical_stay(card["stay"])
                    if stay in stays:
                        current.setdefault(stays.index(stay), []).append(card)
                groups.update(
                    {index: (presentation.get("turn"), cards) for index, cards in current.items()}
                )
            persona = "family" if final.child_ages else "general"
            inputs = [
                (_basket(cards, stays[index]), _lodging_budget(request), persona, turn, index)
                for index, (turn, cards) in sorted(groups.items())
            ]
        except KeyError:
            failures.append("unmapped_hotel_evidence")
        except (TypeError, ValueError) as error:
            reason = str(error)
            failures.append(
                reason
                if reason
                in {
                    "partner_disclosure",
                    "price_unverified",
                    "hotel_features_unverified",
                    "budget_currency_unverified",
                }
                else "invalid_hotel_evidence"
            )
    sheet = dict(
        parameter_version=registry.version,
        parameter_state=registry.state,
        data_source="synthetic",
        soft_model=None,
        violations=failures,
        passed=not failures,
        groups=[],
        booking_probability=0.0,
        expected_revenue_jpy=0.0,
        trust_discount=1.0,
        total_jpy=0.0,
    )
    if failures:
        return sheet
    cards = [
        score(hotels, budget, persona, registry, apply_trust=apply_trust)
        for hotels, budget, persona, _, _ in inputs
    ]
    failures.extend(code for card in cards for code in card.violations)
    revenue = math.fsum(card.expected_revenue_jpy for card in cards)
    discounted = math.fsum(card.expected_revenue_jpy * card.trust_discount for card in cards)
    return {
        **sheet,
        "passed": not failures,
        "groups": [
            {
                "score": asdict(card),
                "budget_jpy": budget,
                "persona": persona,
                "turn": turn,
                "stay": stays[index],
                "segment": index,
                "inputs": [hotel.model_dump(mode="json") for hotel in hotels],
            }
            for card, (hotels, budget, persona, turn, index) in zip(cards, inputs, strict=True)
        ],
        "booking_probability": 1 - math.prod(card.no_booking for card in cards),
        "expected_revenue_jpy": revenue,
        "trust_discount": discounted / revenue if revenue else 1.0,
        "total_jpy": discounted if not failures else 0.0,
    }
