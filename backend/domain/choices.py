"""服务端拥有的有界选择卡与通用表单；模型只能请求类型或提供题目，不能决定交通/节奏选项和写入位置。"""

import re
from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from backend.domain.room_choices import CHOICE_VALUES, ROOM_CHOICES, recognized_room_choices
from backend.domain.travel_request import (
    PACE_ALIASES,
    RequestPatch,
    Text,
    TravelRequest,
    pace_of,
    trip_segments,
)

type ChoiceKind = Literal["pace", "form", "budget_relaxation", "memory_confirm", "hotel_assign"]
KEY = r"^[a-z][a-z0-9_]*$"
Answers = Annotated[dict[str, tuple[Text, ...]], Field(max_length=20)]
TEXT_MAX = 40


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
    # 合并选择卡的自由文本：与选项二选一，答案键为“{key}_text”；falsy时不序列化，旧卡形状不变。
    allow_text: bool = Field(default_factory=lambda: False, exclude_if=lambda value: not value)
    text_kind: Literal["time", "text"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    placeholder: str | None = Field(
        default=None, max_length=TEXT_MAX, exclude_if=lambda value: value is None
    )
    text: str | None = Field(
        default=None, max_length=TEXT_MAX, exclude_if=lambda value: value is None
    )

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
        if (self.text_kind or self.placeholder or self.text) and not self.allow_text:
            raise ValueError("只有允许自由文本的题目才能设置文本类型或文本")
        return self


class ChoiceForm(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    # purpose=trip_ask：服务端生成的合并选择卡(至多11题，全部可不答)；其余表单仍至多5题。
    purpose: Literal["trip_ask"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    groups: tuple[FormGroup, ...] = Field(min_length=1, max_length=11)

    @model_validator(mode="after")
    def unique_keys(self) -> "ChoiceForm":
        if len({group.key for group in self.groups}) != len(self.groups):
            raise ValueError("题目key不能重复")
        if self.purpose is None and len(self.groups) > 5:
            raise ValueError("普通表单至多5题")
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


class ChoicePick(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    choice_id: UUID
    option_id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_-]*$")


class ChoiceSelection(ChoicePick):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    answers: Answers | None = Field(default=None, exclude_if=lambda value: value is None)
    # 同一轮的其他记忆确认卡：一次提交统一记录，只允许记忆卡。
    also: tuple[ChoicePick, ...] = Field(
        default=(), max_length=5, exclude_if=lambda value: not value
    )


class AssignInfo(BaseModel):
    """hotel_assign卡的内容：用户贴的酒店被归入哪个住宿段；needs_city时服务端判不出城市。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    hotel_name: str = Field(min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    check_in: date | None = None
    check_out: date | None = None
    needs_city: bool = False

    @model_validator(mode="after")
    def consistent(self) -> "AssignInfo":
        unplaced = (self.city is None, self.check_in is None, self.check_out is None)
        if any(unplaced) != all(unplaced) or all(unplaced) != self.needs_city:
            raise ValueError("需要城市时不能带城市和日期，否则必须完整")
        return self


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
    assign: AssignInfo | None = Field(default=None, exclude_if=lambda value: value is None)
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: AwareDatetime | None = None
    answered_option_id: str | None = None
    stale: bool = False
    # 合并记忆确认卡：页面预选的选项(记住)；其余卡不设置，不序列化。
    default_option_id: str | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def valid_options(self) -> "ChoiceCard":
        if self.kind == "hotel_assign":
            wanted = ({"confirm", "deny"}, {"deny", "dismiss"})
            if (
                self.assign is None
                or self.form is not None
                or {option.option_id for option in self.options} != wanted[self.assign.needs_city]
            ):
                raise ValueError("归段确认卡需要归段信息和确认/否(或填写城市/不选)两个选项")
        elif self.assign is not None:
            raise ValueError("只有归段确认卡可以带归段信息")
        elif self.kind == "form":
            if (
                self.form is None
                or len(self.options) != 1
                or self.options[0].option_id != "confirm"
            ):
                raise ValueError("表单卡需要题目和统一确认操作")
        elif self.form is not None or len(self.options) < 2:
            raise ValueError("普通选择卡需要2至3个选项，不能混入表单")
        ids = {option.option_id for option in self.options}
        if (
            len(ids) != len(self.options)
            or (self.answered_option_id is not None and self.answered_option_id not in ids)
            or (self.default_option_id is not None and self.default_option_id not in ids)
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


def answered_form(form: ChoiceForm, answers: dict[str, tuple[str, ...]]) -> ChoiceForm:
    """提交后把答案写回预选；时间有更正则显示更正后的原文。"""
    groups = []
    for group in form.groups:
        update: dict[str, object] = {"selected": answers.get(group.key, ())}
        if group.kind == "times":
            corrected = answers.get("times_corrected")
            update.update(shown=corrected or group.shown)
        if group.allow_text:
            typed = answers.get(f"{group.key}_text")
            update.update(text=typed[0].strip() if typed else None)
        groups.append(group.model_copy(update=update))
    return ChoiceForm(groups=tuple(groups), purpose=form.purpose)


def form_patch(
    request: TravelRequest, form: ChoiceForm, answers: dict[str, tuple[str, ...]]
) -> RequestPatch:
    """答案全部通过服务端校验才生成补丁：transport/pace进类型字段，其余仅写入约束文本。"""
    if form.purpose == "trip_ask":
        return trip_ask_patch(request, form, answers)
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


# ---- 合并选择卡(trip_ask)：一张卡问完仍未定的行程信息 ----

ANY = FormOption(option_id="any", label="无要求/不确定")
TIME_ANY = FormOption(option_id="any", label="不确定")


def _options(*pairs: tuple[str, str]) -> tuple[FormOption, ...]:
    return tuple(FormOption(option_id=i, label=label) for i, label in pairs)


# key -> (题目, 选项, 文本类型或None, 提示)；顺序即用户给定的提问顺序。
TRIP_ASK_SPECS: dict[str, tuple[str, tuple[FormOption, ...], str | None, str]] = {
    # 儿童年龄是酒店报价的必填条件：未知时在卡里问(没有儿童=[]；有儿童必须在文字框填年龄)。
    "children": (
        "同行儿童",
        _options(("none", "没有儿童"), ("has", "有儿童")),
        "text",
        "有儿童请填年龄，如 5岁、8岁",
    ),
    "pace": (
        "旅行节奏",
        _options(("relaxed", "轻松"), ("standard", "标准"), ("intensive", "特种兵")) + (ANY,),
        None,
        "",
    ),
    "wake": (
        "平时几点起床",
        _options(
            ("w0630", "6:30 左右"),
            ("w0730", "7:30 左右"),
            ("w0830", "8:30 左右"),
            ("w0930", "9:30 左右"),
            ("w1030", "10:30 以后"),
        )
        + (TIME_ANY,),
        "time",
        "如 7:30，或“看情况”",
    ),
    "evening": (
        "晚上几点结束",
        _options(
            ("e1900", "19:00 左右"),
            ("e2100", "21:00 左右"),
            ("e2200", "22:00 左右"),
            ("e2300", "23:00 以后"),
        )
        + (TIME_ANY,),
        "time",
        "如 22:00，或“看情况”",
    ),
    "arrival": (
        "第一天几点到",
        _options(
            ("a0900", "9:00 前"),
            ("a1200", "中午 12:00 左右"),
            ("a1500", "下午 15:00 左右"),
            ("a1800", "傍晚 18:00 左右"),
            ("a2100", "晚上 21:00 左右"),
        )
        + (TIME_ANY,),
        "time",
        "如 14:30，或航班/车次",
    ),
    "departure": (
        "最后一天几点走",
        _options(
            ("d1200", "中午前"),
            ("d1500", "15:00 左右"),
            ("d1800", "18:00 左右"),
            ("d2100", "晚上 21:00 左右"),
        )
        + (TIME_ANY,),
        "time",
        "如 17:30，或航班/车次",
    ),
    "companion": (
        "这次和谁去",
        _options(
            ("solo", "一个人"),
            ("couple", "情侣"),
            ("family", "家人"),
            ("friends", "朋友"),
            ("other", "其他"),
        )
        + (TIME_ANY,),
        "text",
        "其他同行者(选填)",
    ),
    "lodging": (
        "住宿类型",
        _options(("private", "独立房间"), ("dorm", "接受宿舍"), ("capsule", "接受舱房")) + (ANY,),
        None,
        "",
    ),
    "smoking": ("是否禁烟", _options(("nonsmoking", "禁烟")) + (ANY,), None, ""),
    "bed": ("床型", _options(("twin", "双床"), ("double", "大床")) + (ANY,), None, ""),
    "transport": (
        "交通方式",
        _options(("walk", "步行"), ("transit", "公共交通"), ("taxi", "打车"))
        + (FormOption(option_id="any", label="不确定（按公共交通）"),),
        None,
        "",
    ),
}
# 已确认的长期记忆键可替代哪些组；wake_time/evening_end为memory agent预留的键名。
MEMORY_COVERS = {
    "pace": "pace",
    "transport": "transport",
    "wake": "wake_time",
    "evening": "evening_end",
}
PREFIXES = {
    "wake": ("平时起床：", "soft"),
    "evening": ("晚上结束：", "soft"),
    "companion": ("同行：", "soft"),
    "arrival": ("第一天抵达：", "hard"),
    "departure": ("最后一天离开：", "hard"),
}
PACE_BY_OPTION = {option.option_id: option.value for option in pace_options()}
_TIME = re.compile(r"\d[:：]\d{2}|\d\s*[点時时]")


def _has_prefix(request: TravelRequest, prefix: str) -> bool:
    return any(
        text.startswith(prefix) for text in (*request.hard_constraints, *request.soft_constraints)
    )


def _timed(request: TravelRequest, role: str, words: str) -> bool:
    return _has_prefix(request, PREFIXES[role][0]) or any(
        re.search(words, text) and _TIME.search(text) and not re.search("每天|每日", text)
        for text in request.hard_constraints
    )


def has_lodging(request: TravelRequest) -> bool:
    segments = trip_segments(request)
    return not segments or any(segment.depart > segment.arrive for segment in segments)


def trip_ask_form(
    request: TravelRequest, tasks: tuple[str, ...], memory_known: frozenset[str] = frozenset()
) -> ChoiceForm | None:
    """仍未定的行程信息合并成一张卡；request/已确认长期记忆已有的组不出现，没有未定组则返回None。"""
    itinerary = "itinerary" in tasks
    hotels = bool({"itinerary", "hotel_comparison"} & set(tasks))
    room = recognized_room_choices(request.hard_constraints)
    unknown = {
        "children": request.child_ages is None,
        "pace": itinerary and pace_of(request) is None,
        "wake": itinerary and not _has_prefix(request, PREFIXES["wake"][0]),
        "evening": itinerary and not _has_prefix(request, PREFIXES["evening"][0]),
        "arrival": itinerary and not _timed(request, "arrival", "抵达|到达"),
        "departure": itinerary and not _timed(request, "departure", "返程|离开|返回|回程"),
        "companion": itinerary and not _has_prefix(request, PREFIXES["companion"][0]),
        "transport": itinerary and request.transport is None,
        **{
            key: hotels and has_lodging(request) and not (ROOM_CHOICES[key] & room)
            for key in ("lodging", "smoking", "bed")
        },
    }
    keys = [
        key for key in TRIP_ASK_SPECS if unknown[key] and MEMORY_COVERS.get(key) not in memory_known
    ]
    if not keys:
        return None
    groups = []
    for key in keys:
        label, options, text_kind, placeholder = TRIP_ASK_SPECS[key]
        groups.append(
            FormGroup.model_validate(
                {
                    "key": key,
                    "label": label,
                    "options": options,
                    "allow_text": text_kind is not None,
                    "text_kind": text_kind,
                    "placeholder": placeholder or None,
                }
            )
        )
    return ChoiceForm(purpose="trip_ask", groups=tuple(groups))


def _without_prefix(values: tuple[str, ...], prefix: str) -> tuple[str, ...]:
    return tuple(text for text in values if not text.startswith(prefix))


def _without_room_group(values: tuple[str, ...], key: str) -> tuple[str, ...]:
    return tuple(t for t in values if not (recognized_room_choices((t,)) & ROOM_CHOICES[key]))


_AGE = re.compile(r"(\d{1,2})\s*(?:岁|歲|周岁|y|yo)?", re.IGNORECASE)


def child_ages_from_text(text: str) -> tuple[int, ...]:
    """“5岁、8岁”->(5, 8)；只收0至17的整数，识别不出或越界就拒绝，绝不猜。"""
    ages = tuple(int(n) for n in _AGE.findall(text))
    if not ages or len(ages) > 8 or any(age > 17 for age in ages):
        raise ValueError("儿童年龄需为0至17的数字，如 5岁、8岁")
    return ages


def trip_ask_patch(
    request: TravelRequest, form: ChoiceForm, answers: dict[str, tuple[str, ...]]
) -> RequestPatch:
    """合并卡答案->补丁：只写用户明确选的值；any不写(交通any是标签已明示的公共交通)。"""
    by_key = {group.key: group for group in form.groups}
    text_keys = {f"{key}_text" for key, group in by_key.items() if group.allow_text}
    if set(answers) - by_key.keys() - text_keys:
        raise ValueError("答案包含卡片没有的题目")
    hard, soft = request.hard_constraints, request.soft_constraints
    typed: dict[str, object] = {}
    for key, group in by_key.items():
        ids, texts = answers.get(key, ()), answers.get(f"{key}_text")
        labels = {option.option_id: option.label for option in group.options}
        if len(set(ids)) != len(ids) or not set(ids) <= set(labels) or len(ids) > 1:
            raise ValueError(f"「{group.label}」的答案不是有效选项")
        value = ""
        if texts is not None:
            value = texts[0].strip() if len(texts) == 1 else ""
            if not value or len(value) > TEXT_MAX:
                raise ValueError(f"「{group.label}」的文字需为1至{TEXT_MAX}字")
            if ids:
                raise ValueError(f"「{group.label}」的选项与文字只能二选一")
        choice = ids[0] if ids else ""
        if key == "children":
            if choice == "has":
                raise ValueError("有儿童请在文字框填写年龄，如 5岁、8岁")
            if choice == "none":
                typed["child_ages"] = ()
            elif value:
                typed["child_ages"] = child_ages_from_text(value)
        elif key in CHOICE_VALUES and choice:  # 房型三组：无要求也是用户明确回答的规范值
            hard = (*_without_room_group(hard, key), CHOICE_VALUES[key][choice])
        elif choice == "any" or not (choice or value):
            if choice == "any" and key == "transport":
                typed["transport"] = "transit"
        elif key == "pace":
            hard = (*without_pace(hard), f"节奏：{PACE_BY_OPTION[choice]}")
            soft = without_pace(soft)
        elif key == "transport":
            typed["transport"] = choice
        else:
            prefix, target = PREFIXES[key]
            shown = value or labels[choice]
            hard, soft = _without_prefix(hard, prefix), _without_prefix(soft, prefix)
            if target == "hard":
                hard = (*hard, prefix + shown)
            else:
                soft = (*soft, prefix + shown)
    return RequestPatch.model_validate(
        {
            "expected_revision": request.revision,
            "set": {**typed, "hard_constraints": hard, "soft_constraints": soft},
        }
    )
