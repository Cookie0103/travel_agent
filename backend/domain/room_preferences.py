"""房型名称的有限资格提示；未识别到限制不等同适合。"""

import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from backend.domain.travel_request import TravelRequest


class RoomAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    room_tags: tuple[str, ...] = ()
    qualification_unknown: bool = False
    room_preference_mismatch: bool = False


def room_assessment(name: str, request: TravelRequest | None) -> RoomAssessment:
    dorm = bool(re.search(r"宿舍|ドミトリー|\bdorm(?:itory)?\b", name, re.I))
    capsule = bool(re.search(r"舱房|胶囊|カプセル|\bcapsule\b", name, re.I))
    restricted = bool(
        re.search(
            r"(?:女性|男性|女士|男士|学生|会员|会員)(?:専用|限定|专用)|"
            r"\b(?:female|male|women|men|student|member)[ -]only\b",
            name,
            re.I,
        )
    )
    private = request is not None and "住宿：独立房间" in request.hard_constraints
    tags = tuple(
        tag for found, tag in ((dorm, "宿舍"), (capsule, "舱房"), (restricted, "资格限定")) if found
    )
    return RoomAssessment(
        room_tags=tags + ("仅按房型名称识别", "未核实全部资格"),
        qualification_unknown=restricted,
        room_preference_mismatch=private and (dorm or capsule),
    )


def room_order(names: Sequence[str], request: TravelRequest | None) -> tuple[int, ...]:
    assessed = [room_assessment(name, request) for name in names]
    return tuple(
        sorted(
            range(len(names)),
            key=lambda i: assessed[i].qualification_unknown or assessed[i].room_preference_mismatch,
        )
    )


def room_preferences_question(request: TravelRequest) -> str | None:
    accepted = (
        (
            "住宿方式（独立房间、接受宿舍/舱房或无要求）",
            {"住宿：独立房间", "住宿：接受宿舍", "住宿：接受舱房", "住宿：无要求"},
        ),
        ("禁烟偏好（禁烟或无要求）", {"房型：禁烟", "房型：无要求"}),
        ("床型（双床、大床或无要求）", {"床型：双床", "床型：大床", "床型：无要求"}),
    )
    missing = [
        label
        for label, values in accepted
        if len(values.intersection(request.hard_constraints)) != 1
    ]
    return "酒店查询前，请明确房型偏好：" + "、".join(missing) + "。" if missing else None
