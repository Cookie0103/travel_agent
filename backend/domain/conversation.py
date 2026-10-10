"""有界旅行待办与追问元数据；事实、缺项和完成证明由业务服务决定。"""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.domain.room_choices import missing_room_choices
from backend.domain.travel_request import (
    TravelRequest,
    hotel_search_location_required,
    lodging_budget_relation,
    pace_of,
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


class ConversationStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_revision: int = Field(strict=True, ge=0)
    goals: tuple[Task, ...] | None = Field(default=None, min_length=1, max_length=2)
    awaiting_field: Question | None = None
    cancel: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def valid_state(self) -> Self:
        if self.goals and len(set(self.goals)) != len(self.goals):
            raise ValueError("任务不可重复")
        if self.cancel and (self.goals or self.awaiting_field):
            raise ValueError("取消时不能同时记录新任务或追问")
        return self


def task_missing(
    request: TravelRequest, task: Task, *, live_hotels: bool = False
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
        fields.extend(missing_room_choices(request.hard_constraints))
    elif request.transport is None:
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
    if task == "itinerary" and pace_of(request) is None:
        fields.append("pace")
    return tuple(fields)


def conversation_view(
    state: ConversationState, request: TravelRequest, *, live_hotels: bool = False
) -> dict[str, object]:
    missing = list(
        dict.fromkeys(
            key
            for task in state.pending_tasks
            for key in task_missing(request, task, live_hotels=live_hotels)
        )
    )
    return {
        "pending_tasks": list(state.pending_tasks),
        "awaiting_field": state.awaiting_field if state.awaiting_field in missing else None,
        "missing_fields": missing,
        "ready_tasks": [
            task
            for task in state.pending_tasks
            if not task_missing(request, task, live_hotels=live_hotels)
        ],
        "nights": (request.end_date - request.start_date).days
        if request.start_date and request.end_date
        else None,
        "lodging_budget_optional": (
            request.lodging_budget is None and "lodging_budget" not in missing
        ),
    }
