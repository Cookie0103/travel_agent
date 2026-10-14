"""多轮确定性探针；缺少身份/时间证据记未知，不从回答猜页面状态。"""

import re
from collections.abc import Mapping, Sequence
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter

from backend.domain.execution import RuntimeEvent
from backend.domain.plans import SavedPlan
from backend.domain.travel_request import TripSegment
from eval.claims import claim_consistency

DENIAL = r"没说|没有|未知|不知道|不清楚|不确定|未提供|还没|并未|未记录|尚未确认|未确认"


def recalled(answer: str, *, long_term: bool) -> bool:
    clauses = re.split(r"[。！？\n；，,]|但是|不过|然而|但", answer)
    if long_term:
        for clause in clauses:
            if "特种兵" not in clause:
                continue
            negative = re.search(
                rf"(?:{DENIAL}|不喜欢|不爱|讨厌).{{0,6}}特种兵|"
                rf"特种兵.{{0,6}}(?:{DENIAL})",
                clause,
            )
            denial = re.search(
                rf"(?:{DENIAL}).{{0,6}}(?:记录|偏好|节奏|知道)|"
                rf"(?:记录|偏好|节奏|知道).{{0,6}}(?:{DENIAL})",
                clause,
            )
            if not negative and not denial:
                return True
        return False
    if any(word in answer for word in ("一个人", "单人", "独自", "solo")):
        return False
    return any(
        re.search(
            rf"(?:{DENIAL}).{{0,6}}(?:同行|几个人|出行人数|同伴)|"
            rf"(?:同行|几个人|出行人数|同伴).{{0,6}}(?:{DENIAL})",
            clause,
        )
        for clause in clauses
    )


def saved_items_cover_segments(saved: SavedPlan | None, conditions: Mapping[str, object]) -> bool:
    if saved is None or len(saved.content.hotel_stays) != 3:
        return False
    segments = TypeAdapter(tuple[TripSegment, ...]).validate_python(conditions.get("segments"))
    if len(segments) != 3:
        return False
    expected = {
        segment.arrive + timedelta(days=offset)
        for segment in segments
        for offset in range((segment.depart - segment.arrive).days)
    }
    expected.add(segments[-1].depart)  # 行程包含最后退房当天；与产品日期校验一致。
    actual = {item.start.astimezone(ZoneInfo("Asia/Tokyo")).date() for item in saved.content.items}
    return expected <= actual and {
        (stay.check_in, stay.check_out) for stay in saved.content.hotel_stays
    } == {(segment.arrive, segment.depart) for segment in segments}


def budget_card(data: Mapping[str, object]) -> tuple[str, int, Decimal] | None:
    if data.get("component") != "choice" or data.get("kind") != "budget_relaxation":
        return None
    session, revision, options = (
        data.get("session_id"),
        data.get("expected_revision"),
        data.get("options"),
    )
    if not isinstance(session, str) or type(revision) is not int or not isinstance(options, list):
        return None
    for option in options:
        if not isinstance(option, dict) or option.get("option_id") != "accept":
            continue
        label = option.get("label")
        if isinstance(label, str) and (match := re.search(r"¥([\d,]+(?:\.\d+)?)", label)):
            return session, revision, Decimal(match.group(1).replace(",", ""))
    return None


def no_reoffer_after_decline(dialogue: Sequence[Mapping[str, object]]) -> bool | None:
    cards: dict[str, tuple[str, int, Decimal]] = {}
    declined: set[tuple[str, int, Decimal]] = set()
    unknown = False
    for turn in dialogue:
        action = turn.get("user")
        if (
            isinstance(action, dict)
            and action.get("kind") == "choice"
            and action.get("option_id") == "keep"
        ):
            key = cards.get(str(action.get("choice_id")))
            if key is None:
                unknown = True
            else:
                declined.add(key)
        presentations = turn.get("presentations")
        if not isinstance(presentations, list):
            unknown = True
            continue
        for event in presentations:
            presentation = event.get("presentation") if isinstance(event, dict) else None
            data = presentation.get("data") if isinstance(presentation, dict) else None
            if not isinstance(data, dict) or data.get("kind") != "budget_relaxation":
                continue
            key = budget_card(data)
            if key is None:
                unknown = True
                continue
            # 历史中已回答/失效的卡不是再次邀请接受。
            if key in declined and not data.get("answered_option_id") and not data.get("stale"):
                return False
            cards[str(data.get("choice_id"))] = key
    return None if unknown or not declined else True


def dialogue_claims(
    dialogue: Sequence[Mapping[str, object]], events: tuple[RuntimeEvent, ...]
) -> list[dict[str, bool | None]]:
    groups: dict[str, list[RuntimeEvent]] = {}
    for event in events:
        groups.setdefault(str(event.context.run_id), []).append(event)
    turns = [turn for turn in dialogue if "status" in turn]
    # 老轨迹未存run_id：只有run总数、顺序、session和presentation都吻合才恢复。
    if len(groups) != len(turns):
        return [{"passed": None, "card": None, "retry": None, "expiry": None}]
    results: list[dict[str, bool | None]] = []
    for turn, (run_id, group) in zip(turns, groups.items(), strict=True):
        if turn.get("session_id") != str(group[0].context.session_id) or (
            turn.get("run_id") is not None and turn.get("run_id") != run_id
        ):
            results.append({"passed": None, "card": None, "retry": None, "expiry": None})
            continue
        presentations = turn.get("presentations")
        if isinstance(presentations, list) and any(
            isinstance(event, dict)
            and isinstance(context := event.get("context"), dict)
            and context.get("run_id") != run_id
            for event in presentations
        ):
            results.append({"passed": None, "card": None, "retry": None, "expiry": None})
            continue
        results.append(claim_consistency(str(turn.get("answer", "")), tuple(group)))
    return results


def claims_pass(results: Sequence[Mapping[str, bool | None]]) -> bool | None:
    return (
        False
        if any(r.get("passed") is False for r in results)
        else (None if not results or any(r.get("passed") is None for r in results) else True)
    )
