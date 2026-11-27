"""按所在地和日期核对降水与有证据的雨天备选。"""

from collections.abc import Mapping
from datetime import date
from uuid import UUID

from backend.domain.catalog import SIGHTSEEING_CATEGORIES, Place, inferred_indoor
from backend.domain.evidence import EvidenceRecord
from backend.domain.itinerary import CheckStatus, ItineraryProposal, ValidationCheck
from backend.domain.opening_hours import TOKYO
from backend.domain.regional_rules import place_opening_state
from backend.domain.travel_request import city_key, same_city
from backend.domain.validation_levels import rule_status

type RainForecast = Mapping[tuple[str, date], int | None]


def rain_checks(
    proposal: ItineraryProposal,
    places: list[Place | None],
    evidence: dict[UUID, EvidenceRecord],
    forecast: RainForecast,
    threshold: int,
) -> list[ValidationCheck]:
    by_city = {(city_key(city), day): probability for (city, day), probability in forecast.items()}
    checks: list[ValidationCheck] = []
    unknown_days: set[tuple[str, date]] = set()
    for index, (item, place) in enumerate(zip(proposal.items, places, strict=True)):
        if place is None or place.category.strip().casefold() not in SIGHTSEEING_CATEGORIES:
            continue
        indoor = place.indoor if place.indoor is not None else inferred_indoor(place.category)
        if indoor is True:
            continue
        key = (city_key(place.city), item.start.astimezone(TOKYO).date())
        probability = by_city.get(key)
        if probability is None and key in unknown_days:
            continue
        status: CheckStatus
        if probability is None:
            unknown_days.add(key)
            status, message = "unknown", f"{place.city} {key[1]} 的降水概率未核实。"
        elif probability < threshold:
            continue
        elif indoor is None:
            status, message = "unknown", "该景点的室内外属性未核实，建议准备室内项目。"
        else:
            alternative = (
                evidence.get(item.rain_alternative_place_evidence_id)
                if item.rain_alternative_place_evidence_id
                else None
            )
            backup = (
                Place.model_validate(alternative.value)
                if alternative and alternative.kind == "place" and alternative.status == "verified"
                else None
            )
            valid = (
                backup is not None
                and alternative is not None
                and backup.place_id == alternative.entity_id
                and backup.place_id != place.place_id
                and same_city(backup.city, place.city)
                and (
                    backup.indoor if backup.indoor is not None else inferred_indoor(backup.category)
                )
                is True
                and item.end > item.start
                and place_opening_state(backup, item.start, item.end) == "open"
            )
            status = rule_status("rain_plan", valid)
            message = (
                f"降水概率 {probability}%，室内备选为「{backup.name}」，该时段营业。"
                if valid and backup is not None
                else f"降水概率 {probability}%，请换室内项目或提供同城且该时段可用的室内备选。"
            )
        checks.append(
            ValidationCheck(
                subject=f"item:{index}", status=status, code="rain_plan", message=message
            )
        )
    return checks
