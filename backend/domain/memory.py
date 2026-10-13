"""经用户确认的闭合偏好事实；来源核对不替模型做语义判断。"""

import unicodedata
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

type MemoryKey = Literal[
    "pace",
    "transport",
    "lodging_type",
    "room_type",
    "smoking",
    "dietary",
    "interest",
    "avoid",
    "companion_pattern",
    "budget_style",
]
type MemoryScope = Literal["long_term", "trip"]
type MemoryStatus = Literal["proposed", "active", "rejected", "superseded", "deleted"]
type MemorySource = Literal["user_utterance", "manual", "migrated"]
ENUM_VALUES = {
    "pace": {"标准", "特种兵", "慢节奏"},
    "transport": {"walk", "transit", "taxi"},
    "lodging_type": {"hotel", "hostel", "ryokan", "apartment"},
    "room_type": {"private", "dorm", "capsule", "any"},
    "smoking": {"nonsmoking", "any"},
    "companion_pattern": {"solo", "couple", "family", "friends"},
    "budget_style": {"economy", "balanced", "premium"},
}
VALUE_GUIDE = (
    "; ".join(f"{key}: {', '.join(sorted(values))}" for key, values in ENUM_VALUES.items())
    + "; dietary/interest/avoid: 用户原意的简短文本，最多80字"
)
KEY_LABELS = {
    "pace": "旅行节奏",
    "transport": "交通偏好",
    "lodging_type": "住宿类型",
    "room_type": "房型",
    "smoking": "禁烟偏好",
    "dietary": "饮食",
    "interest": "兴趣",
    "avoid": "希望避免",
    "companion_pattern": "同行方式",
    "budget_style": "预算风格",
}
VALUE_LABELS = {
    "walk": "步行",
    "transit": "公共交通",
    "taxi": "出租车",
    "hotel": "酒店",
    "hostel": "青旅",
    "ryokan": "日式旅馆",
    "apartment": "公寓",
    "private": "独立房间",
    "dorm": "多人宿舍",
    "capsule": "胶囊",
    "any": "不限",
    "nonsmoking": "禁烟",
    "solo": "独自出行",
    "couple": "两人出行",
    "family": "家庭出行",
    "friends": "朋友同行",
    "economy": "节省",
    "balanced": "均衡",
    "premium": "舒适",
    "慢节奏": "比较轻松",
}


def normalize_quote(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def quote_matches(prompt: str, quote: str) -> bool:
    return bool(normalize_quote(quote)) and normalize_quote(quote) in normalize_quote(prompt)


class MemoryOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    op: Literal["ADD", "UPDATE", "INVALIDATE"]
    key: MemoryKey
    value: str | None = Field(default=None, min_length=1, max_length=80, description=VALUE_GUIDE)
    scope: MemoryScope = "long_term"
    quote: str = Field(min_length=1, max_length=200)
    target_fact_id: UUID | None = None

    @model_validator(mode="after")
    def valid_operation(self) -> "MemoryOperation":
        if (self.op == "ADD") != (self.target_fact_id is None):
            raise ValueError("更新/失效须提供目标，ADD不能指定目标")
        if self.op != "INVALIDATE" and self.value is None:
            raise ValueError("ADD/UPDATE须有值")
        if (
            self.value is not None
            and self.key in ENUM_VALUES
            and self.value not in ENUM_VALUES[self.key]
        ):
            raise ValueError("此key不接受该值")
        return self


class MemoryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ops: tuple[MemoryOperation, ...] = Field(min_length=1, max_length=5)


class MemoryFactView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fact_id: UUID
    key: MemoryKey
    value: str | None
    scope: MemoryScope
    session_id: UUID | None
    status: MemoryStatus
    source: MemorySource
    source_run_id: UUID | None
    evidence_quote: str
    valid_from: AwareDatetime | None
    invalidated_at: AwareDatetime | None
    superseded_by: UUID | None
    last_confirmed_at: AwareDatetime | None
    created_at: AwareDatetime
