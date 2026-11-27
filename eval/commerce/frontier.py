"""用冻结评测世界离线粗扫商业政策，并分别检查两个划分的拐点。"""

import argparse
import json
import math
from dataclasses import asdict, dataclass
from itertools import permutations, product
from pathlib import Path
from statistics import mean

from data.eval_world.world import load_world
from eval.commerce.checks import Split, load_cases, walking_minutes
from eval.commerce.parameters import Policy, Registry, load_parameters
from eval.commerce.score import Candidate, Scorecard, score

DEFAULT_OUTPUT = Path(".cache/eval-commerce/policy-provisional.json")
GRID = tuple(product((1 / 3, 2 / 3, 1.0), (0.7, 0.8, 0.9), (0.25, 0.5, 1.0), (0.0, 0.1, 0.3)))


@dataclass(frozen=True)
class Point:
    policy: Policy
    booking_probability: float
    expected_jpy: float
    groups: int

    def report(self) -> dict[str, object]:
        return {**asdict(self), "policy": self.policy.model_dump(mode="json")}


def samples() -> dict[Split, list[tuple[float, tuple[Candidate, ...]]]]:
    world, commissions = load_world()
    hotels = {hotel.hotel_id: hotel for hotel in world.hotels}
    stations = {station.city: station for station in world.stations}
    groups: dict[Split, list[tuple[float, tuple[Candidate, ...]]]] = {"tune": [], "accept": []}
    for example in load_cases():
        if example.kind != "group_quality":
            continue
        entries = []
        for candidate in example.first:
            hotel = hotels[candidate.id]
            commission = commissions[candidate.id]
            entries.append(
                Candidate(
                    id=candidate.id,
                    price_jpy=hotel.prices_jpy["weekday"][0],
                    rating=hotel.rating,
                    reviews=hotel.reviews,
                    station_minutes=walking_minutes(hotel, stations[hotel.city]),
                    breakfast=hotel.breakfast,
                    partner=commission.partner,
                    commission=commission.basis_points / 10_000,
                )
            )
        groups[example.split].append((example.budget_jpy, tuple(entries)))
    return groups


def evaluate(
    groups: list[tuple[float, tuple[Candidate, ...]]], registry: Registry, policy: Policy
) -> Point:
    config = registry.model_copy(update={"policy": policy})
    best: list[Scorecard] = []
    for budget, hotels in groups:
        # 每组以相同的四种出行类型重排，允许少展示一项或不展示。
        lists = tuple(
            row for count in range(len(hotels) + 1) for row in permutations(hotels, count)
        )
        for persona in ("family", "couple", "business", "budget"):
            candidates = (score(options, budget, persona, config) for options in lists)
            best.append(
                max(
                    (card for card in candidates if card.passed),
                    key=lambda card: (card.total_jpy, card.booking_probability),
                )
            )
    return Point(
        policy,
        mean(card.booking_probability for card in best),
        mean(card.total_jpy for card in best),
        len(best),
    )


def frontier(points: list[Point]) -> list[Point]:
    out = []
    best = -math.inf
    for point in sorted(points, key=lambda p: (-p.booking_probability, -p.expected_jpy)):
        if point.expected_jpy > best:
            out.append(point)
            best = point.expected_jpy
    return out


def knee(points: list[Point]) -> Point | None:
    if len(points) < 3:
        return None
    original, last = points[0], points[-1]
    loss = original.booking_probability - last.booking_probability
    gain = last.expected_jpy - original.expected_jpy
    if loss <= 0 or gain <= 0:
        return None
    candidates = [
        (
            (p.expected_jpy - original.expected_jpy) / gain
            - (original.booking_probability - p.booking_probability) / loss,
            p,
        )
        for p in points[1:-1]
    ]
    distance, middle = max(candidates, key=lambda row: row[0])
    return middle if distance > 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parameters", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    registry = load_parameters(args.parameters) if args.parameters else load_parameters()
    result = {}
    knees = []
    for split, groups in samples().items():
        points = []
        for share, floor, gamma, value in GRID:
            policy = Policy(
                top_count=registry.policy.top_count,
                max_partner_share=share,
                min_partner_relevance=floor,
                gamma=gamma,
                partner_value=value,
            )
            points.append(evaluate(groups, registry, policy))
        tradeoffs = frontier(points)
        best = knee(tradeoffs)
        knees.append(best.policy if best else None)
        result[split] = {
            "frontier": [point.report() for point in tradeoffs],
            "knee": best.report() if best else None,
        }
    report = {
        "status": "provisional-synthetic",
        "parameters": registry.version,
        "settings": len(GRID),
        "knee_method": "归一化收益增幅减去下单概率损失，取距离端点连线最大的内部点",
        "same_knee": knees[0] is not None and knees[0] == knees[1],
        "splits": result,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"政策组合 {len(GRID)} · 同档拐点 {report['same_knee']} · {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
