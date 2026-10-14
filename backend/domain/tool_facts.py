"""供评测诊断的封闭参数事实；不记录自由文本、引用或业务ID。"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from backend.domain.choices import ChoiceKind
from backend.domain.memory import MemoryKey, MemoryScope

ChoiceOptionId = Literal[
    "standard", "intensive", "relaxed", "accept", "keep", "remember", "trip", "reject"
]


class MemoryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: MemoryKey | None = None
    scope: MemoryScope | None = None
    op: Literal["ADD", "UPDATE", "INVALIDATE"] | None = None


class ToolArgumentFacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ops: tuple[MemoryArguments, ...] = Field(default=(), max_length=5)
    component: Literal["hotel_comparison", "itinerary", "choice"] | None = None
    kind: ChoiceKind | None = None
    segment_arrive: date | None = None
    option_id: ChoiceOptionId | None = None


def _fields(
    model: type[BaseModel], raw: dict[str, object], names: tuple[str, ...]
) -> dict[str, object]:
    selected: dict[str, object] = {}
    for name in names:
        if name not in raw:
            continue
        try:
            selected[name] = TypeAdapter(model.model_fields[name].annotation).validate_python(
                raw[name]
            )
        except ValidationError:
            pass  # 未通过封闭类型的值是未知，绝不把错误值变成自由文本。
    return selected


def argument_facts(name: str, arguments: dict[str, object]) -> ToolArgumentFacts:
    data: dict[str, object] = {}
    if name == "propose_memory" and isinstance(ops := arguments.get("ops"), list):
        data["ops"] = tuple(
            MemoryArguments.model_validate(_fields(MemoryArguments, op, ("key", "scope", "op")))
            for op in ops[:5]
            if isinstance(op, dict)
        )
    if name == "present_travel_result":
        data.update(_fields(ToolArgumentFacts, arguments, ("component", "kind")))
    if name == "search_hotel_offers":
        raw = arguments.get("segment_arrive")
        if isinstance(raw, str) and len(raw) == 10:
            try:
                data["segment_arrive"] = date.fromisoformat(raw)
            except ValueError:
                pass
    return ToolArgumentFacts.model_validate(data)
