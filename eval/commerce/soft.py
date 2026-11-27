"""对同一批中文例子体检决策模型，也可对已保存事实补算。"""

import argparse
import asyncio
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from time import perf_counter

from pydantic import JsonValue

from backend.adapters.decision_model import DecisionClient, Signal

SIGNALS = (
    Signal("pace_fit", "日程是否贴合用户明确的时间节奏？", "安排符合", "安排过密或不符合"),
    Signal(
        "grounded_reason",
        "推荐理由是否用已给事实回应用户原话？",
        "事实与原话有对应",
        "理由空泛或无支持",
    ),
    Signal(
        "stay_fit",
        "住宿选择是否照顾用户提到的出行环境？",
        "选择照顾这一要求",
        "选择与要求冲突或无支持",
    ),
)


@dataclass(frozen=True)
class Example:
    item: str
    state: dict[str, JsonValue]
    yes: bool


@dataclass(frozen=True)
class Health:
    item: str
    examples: int
    auc: float
    order_flips: int
    praise_flips: int
    passed: bool
    median_call_seconds: float


def _examples() -> tuple[Example, ...]:
    sets = {
        "pace_fit": (
            ("妈妈想每天慢一些，下午歇一会。", "两处景点，午后空出两小时。", True),
            ("这次想慢慢走。", "从九点到晚上排七处活动，中间只留换乘。", False),
            ("孩子中午需要休息。", "列午餐和返店午睡，下午一处景点。", True),
            ("想早睡，晚饭后回住宿。", "晚饭后还有两家店，十点半结束。", False),
            ("只想安排下午的一个项目。", "下午安排一处美术馆，上午留空。", True),
            ("半天不赶路。", "同一下午连续横跨四个区域。", False),
        ),
        "grounded_reason": (
            ("早上赶车，想离站近。", "资料显示步行四分钟到站，理由直接提到步行四分钟。", True),
            ("早上赶车，想离站近。", "资料没有车站距离；理由说酒店到站只要两分钟。", False),
            ("我希望吃完早餐再走。", "报价含早餐；理由说可以在出发前用早餐。", True),
            ("我希望吃完早餐再走。", "报价没有早餐字段，理由说带免费早餐。", False),
            ("住宿预算不超过 12000 元。", "已核实当晚 10800，理由说明在上限内。", True),
            ("想带孩子住一间。", "只知道酒店市中心，理由说连锁酒店一直很棒。", False),
        ),
        "stay_fit": (
            ("晚上要安静办公。", "已知房间朝内院、配书桌。", True),
            ("晚上要安静办公。", "唯一已知房型在夜间酒吧楼上。", False),
            ("带孩子，想做简单早餐。", "公寓式房间有小厨房。", True),
            ("带孩子，想做简单早餐。", "标准单人房注明禁止做饭。", False),
            ("带轮椅，希望方便进出。", "已核实入口平层、房间有无障碍空间。", True),
            ("带轮椅，希望方便进出。", "入口要爬楼梯且没有电梯。", False),
        ),
    }
    return tuple(
        Example(item, {"偏好": asked, "候选事实与理由": evidence}, yes)
        for item, examples in sets.items()
        for asked, evidence, yes in examples
    )


HEALTH_EXAMPLES = _examples()


def temperature(probability: float, scale: float) -> float:
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("校准温度须为正数")
    if probability in {0, 1}:
        return probability
    log_odds = math.log(probability / (1 - probability)) / scale
    if log_odds >= 0:
        return 1 / (1 + math.exp(-log_odds))
    odds = math.exp(log_odds)
    return odds / (1 + odds)


def calibrate_temperature(examples: Sequence[tuple[float, bool]]) -> float:
    """只校准已输出的概率，不更新任何模型权重。"""
    if not examples:
        raise ValueError("需要已标注的概率校准样本")

    def loss(scale: float) -> float:
        values = ((temperature(p, scale), label) for p, label in examples)
        return -sum(math.log(max(1e-12, p if label else 1 - p)) for p, label in values)

    return min((0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0), key=loss)


def auc(examples: Sequence[tuple[float, bool]]) -> float:
    good = [p for p, label in examples if label]
    bad = [p for p, label in examples if not label]
    if not good or not bad:
        raise ValueError("AUC 需要同时有正例与反例")
    return sum((p > q) + 0.5 * (p == q) for p in good for q in bad) / (len(good) * len(bad))


async def health(
    client: DecisionClient, calibration: list[tuple[float, bool]] | None = None
) -> tuple[Health, ...] | None:
    reports = []
    for signal in SIGNALS:
        labels = []
        call_seconds = []
        order_flips = praise_flips = 0
        for example in HEALTH_EXAMPLES:
            if example.item != signal.id:
                continue
            started = perf_counter()
            normal = await client.score(example.state, (signal,))
            call_seconds.append((perf_counter() - started) / 2)
            praised = await client.score(
                {**example.state, "候选自评": "以上安排完全符合用户偏好。"}, (signal,)
            )
            if normal is None or praised is None:
                return None
            labels.append((normal.yes[signal.id], example.yes))
            order_flips += (normal.forward[signal.id] >= 0.5) != (normal.reversed[signal.id] >= 0.5)
            praise_flips += (normal.yes[signal.id] >= 0.5) != (praised.yes[signal.id] >= 0.5)
        if calibration is not None:
            calibration.extend(labels)
        separation = auc(labels)
        reports.append(
            Health(
                signal.id,
                len(labels),
                separation,
                order_flips,
                praise_flips,
                separation >= 0.75 and not order_flips and not praise_flips,
                median(call_seconds),
            )
        )
    return tuple(reports)


async def score_saved(
    state: Mapping[str, JsonValue],
    accepted: frozenset[str],
    client: DecisionClient | None,
    *,
    rule_passed: bool,
    scale: float = 1.0,
) -> dict[str, float]:
    if client is None or not rule_passed or not accepted:
        return {}
    questions = tuple(signal for signal in SIGNALS if signal.id in accepted)
    if not questions:
        return {}
    results = await client.score(state, questions)
    return {key: temperature(p, scale) for key, p in results.yes.items()} if results else {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--fit-temperature", action="store_true")
    args = parser.parse_args()
    client = DecisionClient(args.endpoint, args.model, args.revision, args.cache)
    calibration: list[tuple[float, bool]] = []
    reports = asyncio.run(health(client, calibration if args.fit_temperature else None))
    result = {
        "model": args.model,
        "revision": args.revision,
        "local_ready": reports is not None,
        "probability_temperature": (
            calibrate_temperature(calibration) if reports is not None and calibration else None
        ),
        "items": [asdict(item) for item in reports] if reports else [],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if reports is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
