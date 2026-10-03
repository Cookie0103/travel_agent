"""读取版本化评测用例；只接受明确规格，不从被测回答反推期望。"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.domain.travel_request import TravelConditions


class InitialState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: TravelConditions = Field(default_factory=TravelConditions)


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(pattern=r"^[a-z0-9-]+$")
    source: str
    adaptation: str
    split: Literal["dev", "test"] = "dev"
    input: str = Field(min_length=1)
    initial_state: dict[str, object] = Field(default_factory=dict)
    data_version: str = "kyoto-fixture-v1"
    fault: str | None = None
    allowed_final_statuses: list[str] = Field(default_factory=lambda: ["completed"])
    required_tools: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(
        default_factory=lambda: ["save_plan", "book_hotel", "confirm_booking"]
    )
    should_have_results: bool = False
    response_rule: Literal["nonempty", "clarify", "unsupported", "out_of_scope"] = "nonempty"


def load_cases(path: Path | tuple[Path, ...], split: str) -> list[Case]:
    cases = [
        Case.model_validate_json(line)
        for source in ((path,) if isinstance(path, Path) else path)
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len({c.case_id for c in cases}) != len(cases):
        raise ValueError("评测 case_id 重复")
    selected = [c for c in cases if c.split == split]
    if not selected:
        raise ValueError("所选用例集为空")
    for case in selected:
        if not set(case.required_tools) <= set(case.allowed_tools):
            raise ValueError("必需工具不在允许集合")
        if case.initial_state:
            try:
                InitialState.model_validate(case.initial_state)
            except ValidationError:
                raise ValueError("尚不支持此初始状态或旅行条件无效") from None
        if case.fault or case.data_version != "kyoto-fixture-v1":
            raise ValueError("评测入口尚不支持此初始状态/故障/数据版本")
    return selected
