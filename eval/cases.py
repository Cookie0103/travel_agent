"""读取版本化评测用例；只接受明确规格，不从被测回答反推期望。"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend.domain.execution import ErrorCode
from backend.domain.preferences import PreferenceValues
from backend.domain.travel_request import TravelConditions
from mock_supplier.scenarios import SupplierFault

type CaseFault = SupplierFault
type BusinessCheck = Literal[
    "hotel_comparison",
    "hotel_unknown_total",
    "plan_draft",
    "one_item_patch",
    "second_afternoon_shift",
    "booking_held",
    "booking_unknown_preserved",
    "request_unchanged",
    "expected_tool_failure",
]


class Dialogue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    user: str = Field(min_length=1, max_length=1000)
    assistant: str = Field(max_length=2000)


class InitialState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: TravelConditions = Field(default_factory=TravelConditions)
    saved_plan: bool = Field(default=False, strict=True)
    locked_afternoon: bool = Field(default=False, strict=True)
    offer: Literal["none", "fresh", "expired", "stale"] = "none"
    booking: Literal["none", "held", "unknown"] = "none"
    preferences: PreferenceValues | None = None
    preferences_deleted: bool = Field(default=False, strict=True)
    history: tuple[Dialogue, ...] = Field(default=(), max_length=40)

    @model_validator(mode="after")
    def valid_setup(self) -> "InitialState":
        if self.locked_afternoon and not self.saved_plan:
            raise ValueError("锁定需要正式行程")
        if self.booking != "none" and self.offer != "fresh":
            raise ValueError("预订初始状态需要新鲜报价")
        if self.saved_plan and (
            not self.request.start_date
            or not self.request.end_date
            or (self.request.end_date - self.request.start_date).days not in {1, 2}
        ):
            raise ValueError("演示正式行程需要二至三日明确条件")
        return self


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(pattern=r"^[a-z0-9-]+$")
    source: str
    adaptation: str
    split: Literal["dev", "test"] = "dev"
    input: str = Field(min_length=1)
    initial_state: dict[str, object] = Field(default_factory=dict)
    data_version: str = "kyoto-fixture-v1"
    fault: CaseFault | None = None
    expected_tool_errors: tuple[ErrorCode, ...] = ()
    business_checks: tuple[BusinessCheck, ...] = ()
    allowed_final_statuses: list[str] = Field(default_factory=lambda: ["completed"])
    required_tools: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(
        default_factory=lambda: ["save_plan", "book_hotel", "confirm_booking"]
    )
    should_have_results: bool = False
    result_requirement: Literal["exact", "optional"] = "exact"
    response_rule: Literal["nonempty", "clarify", "unsupported", "out_of_scope"] = "nonempty"

    @model_validator(mode="after")
    def valid_failure_expectation(self) -> "Case":
        if self.result_requirement == "optional" and not (
            self.fault
            and self.expected_tool_errors
            and "expected_tool_failure" in self.business_checks
        ):
            raise ValueError("可选结果仅用于已检查实际依赖故障的案例")
        return self


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
        if case.data_version != "kyoto-fixture-v1":
            raise ValueError("评测入口尚不支持此数据版本")
        if case.expected_tool_errors and "expected_tool_failure" not in case.business_checks:
            raise ValueError("预期工具异常必须检查实际错误")
    return selected
