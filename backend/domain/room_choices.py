"""房型三个文本组的唯一有限词表；不解析整段自然语言或推断未说出的偏好。"""

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

ROOM_CHOICES = {
    "lodging": {"住宿：独立房间", "住宿：接受宿舍", "住宿：接受舱房", "住宿：无要求"},
    "smoking": {"房型：禁烟", "房型：无要求"},
    "bed": {"床型：双床", "床型：大床", "床型：无要求"},
}
KNOWN_CHOICES = set.union(*ROOM_CHOICES.values())
ALIASES = {
    "住宿：独立房": "住宿：独立房间",
    "独立房间": "住宿：独立房间",
    "房型：禁烟房": "房型：禁烟",
    "禁烟房": "房型：禁烟",
    "床型：大床房": "床型：大床",
    "大床房": "床型：大床",
    "床型：双床房": "床型：双床",
    "双床房": "床型：双床",
    "床型：大床优先": "床型：大床",
    "大床优先": "床型：大床",
    "大床最好": "床型：大床",
    "床型：大床最好": "床型：大床",
    "床型：双床优先": "床型：双床",
    "双床优先": "床型：双床",
    "床型：不限": "床型：无要求",
    "床型：都可以": "床型：无要求",
}


def normalize_room_choices(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        key = value.strip().replace(":", "：")
        canonical = canonical_choice(key) or value
        # 首选的强度原文保留；规范值仅代表已表达，不证明实际房型可满足。
        for item in (
            (value, canonical)
            if canonical != value and ("优先" in value or "最好" in value or "不接受" in value)
            else (canonical,)
        ):
            if item not in KNOWN_CHOICES or item not in normalized:
                normalized.append(item)
    # 旧20项记录必须可读；首选原文和原上限都保留，判定另由同一词表派生。
    return tuple(normalized) if len(normalized) <= 20 else values


def missing_room_choices(values: tuple[str, ...]) -> tuple[str, ...]:
    recognized = recognized_room_choices(values)
    return tuple(
        key for key, choices in ROOM_CHOICES.items() if len(choices.intersection(recognized)) != 1
    )


def preserve_unmentioned_room_choices(
    current: tuple[str, ...], incoming: tuple[str, ...]
) -> tuple[str, ...]:
    """对话更新一组时保留其余全部约束；删除指定文本在来源守卫后显式处理。"""
    mentioned = {key for key, values in ROOM_CHOICES.items() if values.intersection(incoming)}
    retained = [
        value
        for value in current
        if not any(
            key in mentioned and recognized_room_choices((value,)).intersection(choices)
            for key, choices in ROOM_CHOICES.items()
        )
    ]
    return tuple(dict.fromkeys((*incoming, *retained)))


def canonical_choice(value: str) -> str | None:
    key = value.strip().replace(":", "：")
    if re.fullmatch(r"住宿：独立房间[，,（(]不接受(?:宿舍[/、和或]?青旅|宿舍|青旅)[）)]?", key):
        return "住宿：独立房间"
    return ALIASES.get(key, key if key in KNOWN_CHOICES else None)


def recognized_room_choices(values: tuple[str, ...]) -> set[str]:
    return {choice for value in values if (choice := canonical_choice(value)) is not None}


CHOICE_VALUES = {
    "lodging": {
        "private": "住宿：独立房间",
        "dorm": "住宿：接受宿舍",
        "capsule": "住宿：接受舱房",
        "any": "住宿：无要求",
    },
    "smoking": {"nonsmoking": "房型：禁烟", "any": "房型：无要求"},
    "bed": {"twin": "床型：双床", "double": "床型：大床", "any": "床型：无要求"},
}


class RoomPreferencesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    lodging: Literal["private", "dorm", "capsule", "any"] | None = None
    smoking: Literal["nonsmoking", "any"] | None = None
    bed: Literal["twin", "double", "any"] | None = None

    @model_validator(mode="after")
    def explicit_values(self) -> Self:
        if not self.model_fields_set or any(
            getattr(self, key) is None for key in self.model_fields_set
        ):
            raise ValueError("仅提供用户明确表达的房型组；无要求用any，未提项省略")
        return self

    def constraints(self) -> tuple[str, ...]:
        return tuple(
            CHOICE_VALUES[key][value]
            for key in CHOICE_VALUES
            if (value := getattr(self, key)) is not None
        )


def room_choices_view(values: tuple[str, ...]) -> dict[str, str | None]:
    recognized = recognized_room_choices(values)
    return {
        key: next((value for value, label in choices.items() if label in recognized), None)
        if len(ROOM_CHOICES[key] & recognized) == 1
        else None
        for key, choices in CHOICE_VALUES.items()
    }
