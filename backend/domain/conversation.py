"""有界旅行待办与追问元数据；事实、缺项和完成证明由业务服务决定。"""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from backend.domain.travel_request import (
    Transport,
    TravelRequest,
    hotel_search_location_required,
    lodging_budget_relation,
    trip_segments,
)

Task = Literal["hotel_comparison", "itinerary"]
Question = Literal[
    "city",
    "hotel_search_location",
    "start_date",
    "end_date",
    "adults",
    "child_ages",
    "rooms",
    "lodging",
    "smoking",
    "bed",
    "pace",
    "transport",
    "budget_conflict",
    "lodging_budget",
]


class ConversationState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    pending_tasks: tuple[Task, ...] = Field(default=(), max_length=2)
    goal_run_id: UUID | None = None
    awaiting_field: Question | None = None
    safe_after: AwareDatetime | None = Field(default=None, exclude_if=lambda value: value is None)


class ConversationStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_revision: int = Field(strict=True, ge=0)
    goals: tuple[Task, ...] | None = Field(default=None, min_length=1, max_length=2)
    awaiting_field: Question | None = None
    cancel: bool = Field(default=False, strict=True)
    confirm_details: bool = Field(
        default=False,
        strict=True,
        description="仅用户本轮明确确认交通、节奏与已提议时间，或明确更正并确认后设true；先更新条件，不能把含糊的继续当作确认",
    )

    @model_validator(mode="after")
    def valid_state(self) -> Self:
        if self.goals and len(set(self.goals)) != len(self.goals):
            raise ValueError("任务不可重复")
        if self.cancel and (self.goals or self.awaiting_field or self.confirm_details):
            raise ValueError("取消时不能同时记录新任务或追问")
        return self


def task_missing(
    request: TravelRequest,
    task: Task,
    *,
    live_hotels: bool = False,
    transport_default: Transport | None = None,
) -> tuple[str, ...]:
    required = ("city", "start_date", "end_date", "adults", "child_ages")
    fields = [key for key in required if getattr(request, key) is None]
    if task == "hotel_comparison":
        if live_hotels and hotel_search_location_required(request):
            fields.append("hotel_search_location")
        if request.start_date and request.end_date == request.start_date:
            fields.append("overnight_stay")
        if request.rooms is None:
            fields.append("rooms")
        # 房型偏好（住宿方式/禁烟/床型）是可选偏好：未说按“无要求”，不再阻塞查询。
    elif request.transport is None and transport_default is None:
        # 已确认的长期（或本会话trip）交通偏好视为已知：不列缺项，由服务端按默认使用。
        fields.append("transport")
    if (
        task == "itinerary"
        and request.lodging_budget is None
        and not request.lodging_budget_unlimited
        and any(segment.depart > segment.arrive for segment in trip_segments(request))
    ):
        fields.append("lodging_budget")
    if lodging_budget_relation(request).status == "conflict":
        fields.append("budget_conflict")
    # 节奏是可选偏好：未说按“标准”默认（只在回复里说明假设，不写成用户事实），不阻塞规划。
    return tuple(fields)


TRANSPORT_LABELS = {"walk": "步行", "transit": "公共交通", "taxi": "出租车"}


def conversation_view(
    state: ConversationState,
    request: TravelRequest,
    *,
    live_hotels: bool = False,
    transport_default: tuple[Transport, str] | None = None,
) -> dict[str, object]:
    """transport_default=(值, 来源scope)：request没有交通时才生效，不写入request。"""
    default = transport_default[0] if transport_default and request.transport is None else None
    missing = list(
        dict.fromkeys(
            key
            for task in state.pending_tasks
            for key in task_missing(
                request, task, live_hotels=live_hotels, transport_default=default
            )
        )
    )
    defaults = (
        {
            "transport": {
                "value": default,
                "label": TRANSPORT_LABELS[default],
                "source": transport_default[1],
            }
        }
        if default and transport_default
        else None
    )
    return {
        **({"defaults": defaults} if defaults else {}),
        "pending_tasks": list(state.pending_tasks),
        "awaiting_field": state.awaiting_field if state.awaiting_field in missing else None,
        "missing_fields": missing,
        "ready_tasks": [
            task
            for task in state.pending_tasks
            if not task_missing(request, task, live_hotels=live_hotels, transport_default=default)
        ],
        "nights": (request.end_date - request.start_date).days
        if request.start_date and request.end_date
        else None,
        "lodging_budget_optional": (
            request.lodging_budget is None and "lodging_budget" not in missing
        ),
    }
