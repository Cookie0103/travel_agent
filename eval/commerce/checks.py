"""用冻结酒店组构造与评审模型无关的参数检查对。"""

import json
import math
import random
from itertools import batched
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from data.eval_world.world import Hotel, Station, World, load_world
from eval.commerce.parameters import Registry
from eval.commerce.score import Candidate, score

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHECKS = ROOT / "eval" / "cases" / "commerce" / "synthetic-checks-v1.jsonl"
SEED = 20261128
type Kind = Literal["dominance", "budget", "exchange", "group_quality", "placement", "persona"]
type Split = Literal["tune", "accept"]
KINDS: tuple[Kind, ...] = (
    "dominance",
    "budget",
    "exchange",
    "group_quality",
    "placement",
    "persona",
)


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    template: str
    group: str
    split: Split
    kind: Kind
    budget_jpy: float
    first: tuple[Candidate, ...]
    second: tuple[Candidate, ...]
    focus_id: str


def _walking_minutes(hotel: Hotel, station: Station) -> float:
    north = math.radians(hotel.latitude - station.latitude)
    east = math.radians(hotel.longitude - station.longitude)
    a = math.sin(north / 2) ** 2 + (
        math.cos(math.radians(station.latitude))
        * math.cos(math.radians(hotel.latitude))
        * math.sin(east / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(math.sqrt(min(1.0, a))) / 80


def _candidate(hotel: Hotel, station: Station) -> Candidate:
    return Candidate(
        id=hotel.hotel_id,
        price_jpy=hotel.prices_jpy["weekday"][0],
        rating=hotel.rating,
        reviews=hotel.reviews,
        station_minutes=_walking_minutes(hotel, station),
        breakfast=hotel.breakfast,
        partner=False,
        commission=0.10,
    )


def _changed(candidate: Candidate, **updates: object) -> Candidate:
    return Candidate.model_validate({**candidate.model_dump(mode="python"), **updates})


def _comparison(
    kind: Kind, split: Split, group: str, candidates: tuple[Candidate, ...], family: int
) -> Comparison:
    a, b, c = candidates
    budget = 15000.0
    first, second = candidates, candidates
    feature = ""
    if kind == "dominance":
        options = (
            (("price_jpy", a.price_jpy - 800), ("rating", min(5, a.rating + 0.15)))
            if split == "tune"
            else (("station_minutes", a.station_minutes * 0.65), ("breakfast", True))
        )
        feature, value = options[family % len(options)]
        if feature == "breakfast":
            a = _changed(a, breakfast=False)
            second = (a, b, c)
        first = (_changed(a, **{feature: value}), b, c)
    elif kind == "budget":
        narrow = 0.05 if split == "tune" else 0.10
        first = (
            _changed(a, price_jpy=budget * (1 - narrow)),
            _changed(a, id=b.id, price_jpy=budget * (1 + narrow)),
        )
        second = first
    elif kind == "exchange":
        feature = "rating" if family % 2 else "station_minutes"
        basis = _changed(
            a,
            rating=3.5 if split == "tune" else 3.0,
            station_minutes=9.0 if split == "tune" else 12.0,
        )
        if feature == "rating":
            changed = _changed(
                basis, id=b.id, rating=basis.rating + 1, price_jpy=basis.price_jpy + 2700
            )
        else:
            changed = _changed(
                basis,
                id=b.id,
                station_minutes=basis.station_minutes - 1,
                price_jpy=basis.price_jpy + 885,
            )
        first = (basis, changed)
        second = (changed, basis)
    elif kind == "group_quality":
        good_rating, good_walk, bad_rating, bad_walk = (
            (4.6, 5, 3.2, 20) if split == "tune" else (4.5, 7, 3.5, 23)
        )
        first = tuple(
            _changed(hotel, rating=good_rating, station_minutes=good_walk, breakfast=True)
            for hotel in first
        )
        second = tuple(
            _changed(hotel, rating=bad_rating, station_minutes=bad_walk, breakfast=False)
            for hotel in second
        )
    elif kind == "placement":
        ordinary = _changed(a, rating=4.5, station_minutes=5)
        partner = _changed(ordinary, id=b.id, rating=3.9, partner=True, commission=0.13)
        if split == "tune":
            first, second = (ordinary, partner), (partner, ordinary)
        else:
            third = _changed(ordinary, id=c.id, rating=4.3, station_minutes=7)
            first, second = (ordinary, third, partner), (partner, ordinary, third)
    else:
        with_breakfast = _changed(
            a,
            breakfast=True,
            station_minutes=a.station_minutes + (2 if split == "accept" else 0),
        )
        first = (with_breakfast, _changed(a, id=b.id, breakfast=False))
        second = first
    template = f"{kind}/{split}/{feature or ('small' if split == 'tune' else 'wide')}"
    return Comparison(
        id=f"{group}:{kind}",
        group=group,
        split=split,
        template=template,
        kind=kind,
        budget_jpy=budget,
        first=first,
        second=second,
        focus_id=a.id,
    )


def generate(world: World, seed: int = SEED) -> tuple[Comparison, ...]:
    rng = random.Random(seed)
    checks: list[Comparison] = []
    for station in world.stations:
        options = sorted(
            (hotel for hotel in world.hotels if hotel.city == station.city),
            key=lambda hotel: hotel.hotel_id,
        )
        rng.shuffle(options)
        groups = [group for group in batched(options, 3) if len(group) == 3]
        for index, hotels in enumerate(groups):
            split: Split = "tune" if index < round(len(groups) * 0.6) else "accept"
            candidates = tuple(_candidate(hotel, station) for hotel in hotels)
            group = f"{station.city}-{index + 1}"
            checks.extend(_comparison(kind, split, group, candidates, index) for kind in KINDS)
    return tuple(checks)


def _chance(entries: tuple[float, ...]) -> tuple[float, float]:
    first, second = entries
    return first, second


def passes(case: Comparison, params: Registry) -> bool:
    def run(offers: tuple[Candidate, ...], persona: str = "general") -> tuple[float, ...]:
        return tuple(
            hotel.probability for hotel in score(offers, case.budget_jpy, persona, params).hotels
        )

    if case.kind == "dominance":
        return run(case.first)[0] > run(case.second)[0]
    if case.kind == "budget":
        regular = _chance(run(case.first))
        tight = _chance(run(case.first, "budget"))
        return 0 < regular[0] - regular[1] < tight[0] - tight[1]
    if case.kind == "exchange":
        forward, reversed_order = run(case.first), run(case.second)
        a, b = forward[0] + reversed_order[1], forward[1] + reversed_order[0]
        return 0.8 <= a / b <= 1.25
    if case.kind in {"group_quality", "placement"}:
        good = score(case.first, case.budget_jpy, "general", params)
        bad = score(case.second, case.budget_jpy, "general", params)
        return good.passed and good.total_jpy >= bad.total_jpy
    family = _chance(run(case.first, "family"))
    business = _chance(run(case.first, "business"))
    return (family[0] - family[1]) > (business[0] - business[1])


def write_cases(path: Path = DEFAULT_CHECKS) -> tuple[Comparison, ...]:
    world, _ = load_world()
    cases = generate(world)
    path.write_text(
        "".join(case.model_dump_json() + "\n" for case in cases),
        encoding="utf-8",
        newline="\n",
    )
    return cases


def load_cases(path: Path = DEFAULT_CHECKS) -> tuple[Comparison, ...]:
    return tuple(
        Comparison.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


if __name__ == "__main__":
    cases = write_cases()
    groups = {
        split: {
            kind: sum(case.split == split and case.kind == kind for case in cases) for kind in KINDS
        }
        for split in ("tune", "accept")
    }
    print(json.dumps(groups, ensure_ascii=False))
