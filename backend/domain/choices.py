"""服务端拥有的有界选择卡与通用表单；模型只能请求类型或提供题目，不能决定交通/节奏选项和写入位置。"""

import re
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from backend.domain.travel_request import (
    PACE_ALIASES,
    RequestPatch,
    Text,
    TravelRequest,
    pace_of,
)

type ChoiceKind = Literal["pace", "form", "budget_relaxation", "memory_confirm"]
FORM_ROW_KINDS = ("form", "travel_details")  # 数据库旧卡仍存为travel_details，仅在读取边界归一
KEY = r"^[a-z][a-z0-9_]*$"
Answers = Annotated[dict[str, tuple[Text, ...]], Field(max_length=6)]


class ChoiceOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    option_id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=200)


class FormOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    option_id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=40)


class FormGroupInput(BaseModel):
    """模型可提供的题目；transport与pace的选项由服务端固定，模型给的选项会被替换。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(min_length=1, max_length=30, pattern=KEY)
    label: str = Field(min_length=1, max_length=20)
    multi: bool = False
    required: bool = False
    options: tuple[FormOption, ...] = Field(default=(), max_length=6)


class FormGroup(FormGroupInput):
    """kind=times只由服务端按已有时间条件生成：shown为原文，答案yes/no，no时给自由文本更正。"""

    kind: Literal["choice", "times"] = "choice"
    selected: tuple[str, ...] = Field(default=(), max_length=6)  # 预选或已提交的答案
    shown: tuple[Text, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def valid_group(self) -> "FormGroup":
        ids = {option.option_id for option in self.options}
        is_times = self.kind == "times"
        if is_times != bool(self.shown) or is_times != (self.key == "times"):
            raise ValueError("时间题只能由服务端以key=times和已有时间原文生成")
        if len(ids) != len(self.options) or not set(self.selected) <= ids:
            raise ValueError("选项重复或预选值不在选项中")
        if len(self.options) < 2:
            raise ValueError("每个题目需要2至6个选项")
        return self


class ChoiceForm(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    groups: tuple[FormGroup, ...] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def unique_keys(self) -> "ChoiceForm":
        if len({group.key for group in self.groups}) != len(self.groups):
            raise ValueError("题目key不能重复")
        return self


class FormInput(BaseModel):
    """present_form参数：1至4个题目；服务端按需追加时间确认题，校验答案后一次提交。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_revision: int = Field(strict=True, ge=0)
    groups: tuple[FormGroupInput, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def no_reserved_key(self) -> "FormInput":
        if any(group.key == "times" for group in self.groups):
            raise ValueError("times为服务端保留的时间确认题")
        return self


class ChoiceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    choice_id: UUID
    option_id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_-]*$")
    answers: Answers | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="before")
    @classmethod
    def legacy_details(cls, data: object) -> object:
        # 读取边界：旧标签页待发队列里的details(交通、节奏值、时间是否正确)转为answers。
        if not isinstance(data, dict) or "details" not in data:
            return data
        old = {**data}
        details = old.pop("details")
        if isinstance(details, dict):
            pace = {option.value: option.option_id for option in pace_options()}
            answers: dict[str, object] = {
                "transport": [details.get("transport")],
                "pace": [pace.get(str(details.get("pace")))],
            }
            if details.get("times_correct") is not None:
                answers["times"] = ["yes" if details["times_correct"] else "no"]
            if details.get("corrected_times") is not None:
                answers["times_corrected"] = details["corrected_times"]
            old.setdefault("answers", answers)
        return old


class ChoiceCard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    choice_id: UUID = Field(default_factory=uuid4)
    kind: ChoiceKind
    session_id: UUID
    source_run_id: UUID
    expected_revision: int = Field(strict=True, ge=0)
    question: str = Field(min_length=1, max_length=200)
    options: tuple[ChoiceOption, ...] = Field(min_length=1, max_length=3)
    form: ChoiceForm | None = Field(default=None, exclude_if=lambda value: value is None)
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: AwareDatetime | None = None
    answered_option_id: str | None = None
    stale: bool = False

    @model_validator(mode="after")
    def valid_options(self) -> "ChoiceCard":
        if self.kind == "form":
            if (
                self.form is None
                or len(self.options) != 1
                or self.options[0].option_id != "confirm"
            ):
                raise ValueError("表单卡需要题目和统一确认操作")
        elif self.form is not None or len(self.options) < 2:
            raise ValueError("普通选择卡需要2至3个选项，不能混入表单")
        ids = {option.option_id for option in self.options}
        if len(ids) != len(self.options) or (
            self.answered_option_id is not None and self.answered_option_id not in ids
        ):
            raise ValueError("选择卡的选项或已选值不匹配")
        return self


def pace_options() -> tuple[ChoiceOption, ...]:
    return tuple(
        ChoiceOption(option_id=option_id, label=label, value=value)
        for option_id, label, value in (
            ("standard", "标准", "标准"),
            ("intensive", "特种兵", "特种兵"),
            ("relaxed", "比较轻松", "慢节奏"),
        )
    )


def without_pace(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(text for text in values if text.removeprefix("节奏：").strip() not in PACE_ALIASES)


def pace_patch(request: TravelRequest, value: str) -> RequestPatch:
    if value not in {option.value for option in pace_options()}:
        raise ValueError("无效节奏选项")
    return RequestPatch.model_validate(
        {
            "expected_revision": request.revision,
            "set": {
                "hard_constraints": (*without_pace(request.hard_constraints), f"节奏：{value}"),
                "soft_constraints": without_pace(request.soft_constraints),
            },
        }
    )


TRANSPORT_LABELS = (("walk", "步行"), ("transit", "公共交通（公交、地铁为主）"), ("taxi", "打车"))
YES_NO = (FormOption(option_id="yes", label="没问题"), FormOption(option_id="no", label="需要修改"))
TIMES_KEY = "times"


TRANSPORT_PACE_GROUPS = (
    FormGroupInput(key="transport", label="交通方式"),
    FormGroupInput(key="pace", label="旅行节奏"),
)


def canonical_options(key: str) -> tuple[FormOption, ...] | None:
    """transport与pace的选项和含义归服务端，其余题目由模型自拟。"""
    if key == "transport":
        return tuple(FormOption(option_id=i, label=label) for i, label in TRANSPORT_LABELS)
    if key == "pace":
        return tuple(FormOption(option_id=o.option_id, label=o.label) for o in pace_options())
    return None


def shown_times(request: TravelRequest) -> tuple[str, ...]:
    # 不变量：只显示已有条件，不从模型回答或网页猜时间；编辑时展示/替换同一完整条件。
    return tuple(
        text
        for text in request.hard_constraints
        if re.search(r"抵达|到达|返程|离开|返回|回程|出发", text)
        and re.search(r"\d[:：]\d{2}|\d\s*[点時时]", text)
        and not re.search(r"每天|每日", text)
    )


def make_form(
    groups: tuple[FormGroupInput, ...],
    present: dict[str, str | None],
    times: tuple[str, ...],
) -> ChoiceForm:
    """交通/节奏换成服务端选项并预选present中的值；含它们时，已有抵达/离开时间追加为时间确认题。"""
    built = []
    for group in groups:
        fixed = canonical_options(group.key)
        data = group.model_dump()
        if fixed is not None:
            selected = present.get(group.key)
            data.update(options=fixed, multi=False, selected=(selected,) if selected else ())
        built.append(FormGroup.model_validate(data))
    if times and any(group.key in present for group in groups):
        built.append(
            FormGroup(
                key=TIMES_KEY, label="抵达/离开时间", kind="times", options=YES_NO, shown=times
            )
        )
    return ChoiceForm(groups=tuple(built))


def build_form(request: TravelRequest, groups: tuple[FormGroupInput, ...]) -> ChoiceForm:
    pace = next((o.option_id for o in pace_options() if o.value == pace_of(request)), None)
    return make_form(groups, {"transport": request.transport, "pace": pace}, shown_times(request))


def legacy_form(details: dict[str, object]) -> ChoiceForm:
    """读取边界：旧travel_details卡的内容(交通/节奏预选、时间原文)转为表单。"""
    pace = next((o.option_id for o in pace_options() if o.value == details.get("pace")), None)
    times = TypeAdapter(tuple[Text, ...]).validate_python(details.get("time_constraints", ()))
    return make_form(
        TRANSPORT_PACE_GROUPS,
        {
            "transport": str(details["transport"]) if details.get("transport") else None,
            "pace": pace,
        },
        times,
    )


def answered_form(form: ChoiceForm, answers: dict[str, tuple[str, ...]]) -> ChoiceForm:
    """提交后把答案写回预选；时间有更正则显示更正后的原文。"""
    groups = []
    for group in form.groups:
        update: dict[str, object] = {"selected": answers.get(group.key, ())}
        if group.kind == "times":
            corrected = answers.get("times_corrected")
            update.update(shown=corrected or group.shown)
        groups.append(group.model_copy(update=update))
    return ChoiceForm(groups=tuple(groups))


def form_patch(
    request: TravelRequest, form: ChoiceForm, answers: dict[str, tuple[str, ...]]
) -> RequestPatch:
    """答案全部通过服务端校验才生成补丁：transport/pace进类型字段，其余仅写入约束文本。"""
    keys = {group.key for group in form.groups}
    if set(answers) - keys - ({"times_corrected"} if TIMES_KEY in keys else set()):
        raise ValueError("答案包含卡片没有的题目")
    if not any(answers.get(group.key) for group in form.groups):
        raise ValueError("请至少回答一题")
    typed: dict[str, object] = {}
    hard, soft = request.hard_constraints, request.soft_constraints
    for group in form.groups:
        ids = answers.get(group.key, ())
        labels = {option.option_id: option.label for option in group.options}
        if len(set(ids)) != len(ids) or not set(ids) <= set(labels):
            raise ValueError(f"「{group.label}」的答案不是有效选项")
        if len(ids) > 1 and not group.multi:
            raise ValueError(f"「{group.label}」只能选一项")
        if not ids:
            if group.kind == "times" and answers.get("times_corrected") is not None:
                raise ValueError("时间不正确时必须填写更正；确认正确时不能混填更正")
            if group.required:
                raise ValueError(f"请先回答「{group.label}」")
            continue
        if group.key == "transport":
            typed["transport"] = ids[0]
        elif group.key == "pace":
            pace = next(o.value for o in pace_options() if o.option_id == ids[0])
            hard, soft = (*without_pace(hard), f"节奏：{pace}"), without_pace(soft)
        elif group.kind == "times":
            corrected = answers.get("times_corrected")
            if (ids == ("no",)) != (corrected is not None):
                raise ValueError("时间不正确时必须填写更正；确认正确时不能混填更正")
            if corrected is not None:
                if not corrected or any(not t.strip() for t in corrected):
                    raise ValueError("请写出正确的抵达/离开时间")
                hard = (*(t for t in hard if t not in group.shown), *corrected)
        else:
            prefix = f"{group.label}："
            hard = (
                *(t for t in hard if not t.startswith(prefix)),
                prefix + "、".join(labels[i] for i in ids),
            )
            soft = tuple(t for t in soft if not t.startswith(prefix))
    return RequestPatch.model_validate(
        {
            "expected_revision": request.revision,
            "set": {**typed, "hard_constraints": hard, "soft_constraints": soft},
        }
    )
