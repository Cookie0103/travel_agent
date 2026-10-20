"""v3评测题：一行一题的JSONL，加载时即校验；脚本化用户，LLM只在显式facts兜底时出场。"""

import json
import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    model_validator,
)

from backend.adapters.evaluation_faults import EvaluationFault
from backend.domain.choices import Answers
from backend.domain.memory import ENUM_VALUES, MemoryKey, MemoryScope, MemoryStatus
from backend.tools.search import DEFINITIONS as SEARCH_DEFINITIONS
from backend.tools.travel import DEFINITIONS as TRAVEL_DEFINITIONS
from eval.cases import InitialState, MemoryExpected
from eval.v3_tiers import VALIDATOR_TIER

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "eval" / "cases" / "v3.jsonl"
CASE_ID = r"^[a-z0-9][a-z0-9_-]{0,79}$"
CHECK_ID = r"^[a-z0-9][a-z0-9_-]{0,63}$"
TOOL_NAMES = frozenset(d.name for d in (*SEARCH_DEFINITIONS, *TRAVEL_DEFINITIONS))
# 真实线路（live_definitions）不向模型暴露hold_hotel；离线夹具暴露。任何对话都不应预订。
DEFAULT_FORBIDDEN = ("hold_hotel",)

type Category = Literal[
    "main_flow", "ambiguous", "mid_change", "fault", "out_of_scope", "memory", "adversarial"
]
type CardKind = Literal[
    "trip_ask", "form", "pace", "budget_relaxation", "memory_confirm", "hotel_assign"
]
# 每种卡的合法option_id；trip_ask/form的唯一操作是confirm，选择内容放answers。
CARD_OPTIONS: dict[str, frozenset[str]] = {
    "trip_ask": frozenset({"confirm"}),
    "form": frozenset({"confirm"}),
    "pace": frozenset({"standard", "intensive", "relaxed"}),
    "budget_relaxation": frozenset({"accept", "keep"}),
    "memory_confirm": frozenset({"remember", "trip", "reject"}),
    "hotel_assign": frozenset({"confirm", "deny", "dismiss"}),
}
type ValidatorStatusFloor = Literal["verified", "not_conflict"]
type StateKey = Literal["request", "saved_version", "hotel_stays", "bookings", "memory"]
STATE_KEYS = frozenset({"request", "saved_version", "hotel_stays", "bookings", "memory"})


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CardStep(Strict):
    kind: CardKind
    option: str | None = None
    answers: Answers | None = None
    if_missing: Literal["fail", "skip"] = "fail"

    @model_validator(mode="after")
    def valid_option(self) -> "CardStep":
        if self.option is not None and self.option not in CARD_OPTIONS[self.kind]:
            raise ValueError(f"{self.kind}卡没有选项{self.option}")
        if self.answers is not None and self.kind not in {"trip_ask", "form"}:
            raise ValueError("answers只用于trip_ask/form卡")
        return self


class HotelPickStep(Strict):
    rank: Literal["first", "last", "cheapest"] | Annotated[int, Field(ge=0, le=9)] = "first"
    segment: int = Field(default=0, ge=0, le=5)


class Step(Strict):
    say: str | None = Field(default=None, min_length=1, max_length=1000)
    card: CardStep | None = None
    hotel_pick: HotelPickStep | None = None
    new_session: Literal[True] | None = None
    switch_user: str | None = Field(default=None, pattern=r"^[A-Z]$")
    confirm_plan: Literal[True] | None = None

    @model_validator(mode="after")
    def one_action(self) -> "Step":
        actions = [
            name
            for name in ("card", "hotel_pick", "new_session", "switch_user", "confirm_plan")
            if getattr(self, name) is not None
        ]
        if len(actions) > 1:
            raise ValueError("每步只能有一个动作")
        if not actions and self.say is None:
            raise ValueError("每步需要say或一个动作")
        if self.say is not None and actions and actions[0] != "card":
            raise ValueError("say只能与card同步骤出现")
        return self

    @property
    def action(self) -> str:
        return next(
            (
                name
                for name in ("card", "hotel_pick", "new_session", "switch_user", "confirm_plan")
                if getattr(self, name) is not None
            ),
            "say",
        )


class CheckBase(Strict):
    id: str = Field(pattern=CHECK_ID)
    weight: int = Field(default=1, ge=1, le=5)  # 仅软检查使用


class ValidatorCheck(CheckBase):
    """最后一份计划草稿里的validator结果；缺草稿/缺该项按unknown，硬检查不算通过。"""

    type: Literal["validator"]
    code: str = Field(min_length=1, max_length=40)
    subject: str | None = None
    min_status: ValidatorStatusFloor = "verified"
    allow_unknown: Literal[False] = False

    @model_validator(mode="after")
    def known_code(self) -> "ValidatorCheck":
        if self.code not in VALIDATOR_TIER:
            raise ValueError(f"未知validator code：{self.code}；可用：{sorted(VALIDATOR_TIER)}")
        return self


class StateCheck(CheckBase):
    """用eval.metrics.subset_matches比较终态子集；列表长度必须相等。"""

    type: Literal["state"]
    expect: dict[StateKey, JsonValue] = Field(min_length=1)


type DbAssert = Literal[
    "hotel_selected",
    "draft_exists",
    "draft_no_conflict",
    "draft_min_places",
    "plan_saved",
    "no_plan_saved",
    "no_new_orders",
    "memory_active",
    "memory_absent",
]


class DbCheck(CheckBase):
    """数据库断言。hotel_selected需segments；draft_min_places需min_per_day；memory_active需key+scope(+value_contains)；memory_absent需key。"""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    type: Literal["db"]
    assert_: DbAssert = Field(alias="assert")
    segments: int | None = Field(default=None, ge=1, le=6)
    min_per_day: int | None = Field(default=None, ge=1, le=10)
    key: MemoryKey | None = None
    scope: MemoryScope | None = None
    value_contains: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def valid_params(self) -> "DbCheck":
        given = {
            name
            for name in ("segments", "min_per_day", "key", "scope", "value_contains")
            if getattr(self, name) is not None
        }
        needed = {
            "hotel_selected": {"segments"},
            "draft_min_places": {"min_per_day"},
            "memory_active": {"key", "scope"},
            "memory_absent": {"key"},
        }.get(self.assert_, set())
        optional = (
            {"value_contains"}
            if self.assert_ == "memory_active"
            else {"scope"}
            if self.assert_ == "memory_absent"
            else set()
        )
        if not needed <= given or not given <= needed | optional:
            raise ValueError(f"{self.assert_}的参数应为{sorted(needed | optional)}")
        return self


def valid_turn(turn: int | str) -> None:
    if isinstance(turn, int) and not 1 <= turn <= 12:
        raise ValueError("turn应为1..12、last或any")


class ReplyCheck(CheckBase):
    type: Literal["reply"]
    turn: int | Literal["last", "any"] = "last"
    matches: str | None = None
    not_matches: str | None = None

    @model_validator(mode="after")
    def valid_patterns(self) -> "ReplyCheck":
        if self.matches is None and self.not_matches is None:
            raise ValueError("reply检查需要matches或not_matches")
        valid_turn(self.turn)
        for pattern in (self.matches, self.not_matches):
            if pattern is not None:
                try:
                    re.compile(pattern)
                except re.error as error:
                    raise ValueError(f"无效正则：{pattern}") from error
        return self


class CardCheck(CheckBase):
    """某一轮（该轮run发出的）卡片：种类、是否含/不含某题key。"""

    type: Literal["card"]
    turn: int | Literal["last", "any"] = "any"
    kind: CardKind
    has_group: str | None = None
    lacks_group: str | None = None

    @model_validator(mode="after")
    def valid_turn_number(self) -> "CardCheck":
        valid_turn(self.turn)
        return self


class TurnToolCheck(CheckBase):
    """指定轮次实际调用过的工具：called 必须全出现，not_called 必须都不出现。

    trial 级 required/forbidden 只能看并集，改条件后“是否真的按新条件重查”
    这类问题必须按轮断言，所以单列这一类。
    """

    type: Literal["turn_tool"]
    turn: int | Literal["last", "any"] = "last"
    called: tuple[str, ...] = ()
    not_called: tuple[str, ...] = ()

    @model_validator(mode="after")
    def valid_tools(self) -> "TurnToolCheck":
        valid_turn(self.turn)
        if not self.called and not self.not_called:
            raise ValueError("turn_tool检查需要called或not_called")
        unknown = {*self.called, *self.not_called} - TOOL_NAMES
        if unknown:
            raise ValueError(f"未注册的工具名：{sorted(unknown)}")
        if set(self.called) & set(self.not_called):
            raise ValueError("called与not_called不能相交")
        return self


type Check = Annotated[
    ValidatorCheck | StateCheck | DbCheck | ReplyCheck | CardCheck | TurnToolCheck,
    Field(discriminator="type"),
]


class Fallback(Strict):
    policy: Literal["stop", "idk", "facts"] = "stop"
    max_extra_turns: int = Field(default=0, ge=0, le=3)


class MemoryFactExpect(Strict):
    key: MemoryKey
    value_contains: str | None = Field(default=None, min_length=1, max_length=80)
    scope: MemoryScope = "long_term"
    status: MemoryStatus = "active"


class L3Expect(Strict):
    present: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()


class MemorySpec(Strict):
    l1: tuple[MemoryExpected, ...] = ()
    l2: tuple[MemoryFactExpect, ...] = ()
    l3: L3Expect = Field(default_factory=L3Expect)
    l4: tuple[Check, ...] = ()

    @model_validator(mode="after")
    def valid_enum_values(self) -> "MemorySpec":
        for item in self.l1:
            allowed = ENUM_VALUES.get(item.key)
            if allowed is not None and any(
                value is not None and value not in allowed for value in item.values
            ):
                raise ValueError(f"l1的{item.key}值须取自{sorted(allowed)}")
        return self

    @property
    def declared(self) -> bool:
        return bool(self.l1 or self.l2 or self.l3.present or self.l3.absent or self.l4)


class RubricItem(Strict):
    id: str = Field(pattern=CHECK_ID)
    q: str = Field(min_length=1, max_length=300)


class V3Case(Strict):
    case_id: str = Field(pattern=CASE_ID)
    category: Category
    title: str = Field(min_length=1, max_length=200)
    setup: InitialState | None = None
    fault: EvaluationFault | None = None
    # null=只记录延迟、不取消、不影响success；显式设置patience_s才会取消并记为放弃。
    patience_s: int | None = Field(default=None, ge=10, le=3600)
    ttfua_s: int | None = Field(default=None, ge=1, le=3600)
    user_script: tuple[Step, ...] = Field(min_length=1, max_length=12)
    fallback: Fallback = Field(default_factory=Fallback)
    user_facts: dict[str, str] = Field(default_factory=dict)
    hard_checks: tuple[Check, ...] = ()
    soft_checks: tuple[Check, ...] = ()
    required_tools: tuple[str, ...] = ()
    forbidden_tools: tuple[str, ...] = DEFAULT_FORBIDDEN
    memory: MemorySpec = Field(default_factory=MemorySpec)
    rubric: tuple[RubricItem, ...] = Field(min_length=3, max_length=5)
    notes: str = ""

    @model_validator(mode="after")
    def consistent(self) -> "V3Case":
        if (self.fallback.policy == "facts") != bool(self.user_facts):
            raise ValueError("user_facts仅在fallback.policy=facts时提供，且必须非空")
        if self.setup is not None and (self.setup.offer != "none" or self.setup.booking != "none"):
            raise ValueError("v3的setup暂不支持offer/booking（需要专用供应商）")
        if self.fallback.policy == "stop" and self.fallback.max_extra_turns:
            raise ValueError("policy=stop时max_extra_turns须为0")
        unknown = {*self.required_tools, *self.forbidden_tools} - TOOL_NAMES
        if unknown:
            raise ValueError(f"未注册的工具名：{sorted(unknown)}")
        if set(self.required_tools) & set(self.forbidden_tools):
            raise ValueError("required_tools与forbidden_tools不能相交")
        if (
            self.ttfua_s is not None
            and self.patience_s is not None
            and self.ttfua_s > self.patience_s
        ):
            raise ValueError("ttfua_s不能大于patience_s")
        if any(c.weight != 1 for c in self.hard_checks):
            raise ValueError("硬检查不使用weight（必须为1）；weight只用于soft_checks")
        # 上界：每个say/card/hotel_pick最多产生一轮run，再加兜底追加轮次。
        producing = sum(s.action in {"say", "card", "hotel_pick"} for s in self.user_script)
        limit = producing + self.fallback.max_extra_turns
        for check in (*self.hard_checks, *self.soft_checks, *self.memory.l4):
            if isinstance(check, (ReplyCheck, CardCheck, TurnToolCheck)) and isinstance(
                check.turn, int
            ):
                if check.turn > limit:
                    raise ValueError(
                        f"检查{check.id}的turn={check.turn}超过脚本最多产生的{limit}轮run"
                    )
        ids = [c.id for c in (*self.hard_checks, *self.soft_checks, *self.memory.l4)]
        if any(r.id.startswith("g-") for r in self.rubric):
            raise ValueError("rubric id不能以g-开头（保留给通用评审项）")
        ids += [r.id for r in self.rubric]
        if len(ids) != len(set(ids)):
            raise ValueError("检查/rubric id必须唯一")
        if len({s.switch_user for s in self.user_script if s.switch_user}) > 3:
            raise ValueError("switch_user至多3个用户")
        if self.memory.declared and not any(
            s.action in {"new_session", "switch_user"} for s in self.user_script
        ):
            # L3只看新会话的第一轮；没有新会话时L3无意义，L1/L2/L4仍可单会话使用。
            if self.memory.l3.present or self.memory.l3.absent:
                raise ValueError("声明memory.l3需要脚本里有new_session或switch_user")
        return self


def parse_case(line: str) -> V3Case:
    return V3Case.model_validate_json(line)


def load_cases(path: Path = DEFAULT_CASES) -> list[V3Case]:
    cases: list[V3Case] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(parse_case(line))
        except (ValidationError, json.JSONDecodeError) as error:
            raise ValueError(f"{path.name}第{number}行无效：{error}") from error
    seen: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            raise ValueError(f"case_id重复：{case.case_id}")
        seen.add(case.case_id)
    return cases
