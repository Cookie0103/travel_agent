"""旅行待办元数据事务；仅本人当前执行写入，完成由执行器的实际结果触发。"""

from datetime import datetime

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.conversation import ConversationState, conversation_view
from backend.domain.execution import RunContext
from backend.domain.itinerary import HotelStay
from backend.domain.travel_request import TravelRequest
from backend.persistence import runs
from backend.persistence.models import TaskRunRow, TravelRequestRow
from backend.services.common import ServiceError


def stored_state(row: TravelRequestRow) -> ConversationState:
    return ConversationState.model_validate(
        (row.request_details or {}).get("conversation_state") or {}
    )


def save_state(row: TravelRequestRow, state: ConversationState) -> None:
    row.request_details = {
        **(row.request_details or {}),
        "conversation_state": state.model_dump(mode="json"),
    }


async def require_current_run(db: AsyncSession, context: RunContext) -> None:
    run = await runs.owned(db, context.user_id, context.run_id, lock=True)
    if run is None or run.session_id != context.session_id or run.status != "running":
        raise ServiceError(
            409, "conflict", "当前对话已结束或取消，不能覆盖对话状态", "conversation_run_inactive"
        )


async def valid_state(
    db: AsyncSession,
    row: TravelRequestRow,
    context: RunContext,
    *,
    after: datetime | None = None,
) -> tuple[ConversationState, TaskRunRow | None]:
    state = stored_state(row)
    origin = await runs.owned(db, context.user_id, state.goal_run_id) if state.goal_run_id else None
    if origin is None or origin.session_id != context.session_id:
        return ConversationState(), None
    if after and origin.created_at < after:
        # 仅确认服务写入此证明；保留封闭待办，绝不恢复旧原任务正文。
        if state.safe_after is not None and state.safe_after >= after:
            return state, None
        return ConversationState(), None
    return state, origin


async def snapshot(
    db: AsyncSession,
    row: TravelRequestRow,
    request: TravelRequest,
    context: RunContext,
    *,
    after: datetime | None = None,
    live_hotels: bool = False,
) -> dict[str, object]:
    state, origin = await valid_state(db, row, context, after=after)
    return {
        **conversation_view(state, request, live_hotels=live_hotels),
        "goal_prompt": origin.prompt[:1000] if origin else None,
        "goal_prompt_truncated": bool(origin and len(origin.prompt) > 1000),
        "guidance": "原任务文本仅作用户需求参考，当前request为事实。"
        "短答仅回答awaiting_field，不放宽其他条件。住宿地点短答写hotel_search_location，保留city；宽区域地点需要细化，不默认选择那霸。条件齐全后继续ready_tasks；"
        "住宿分项预算未知不必追问，不拆分全程预算。",
    }


def selected_hotel_stays(
    row: TravelRequestRow, context: RunContext, revision: int
) -> tuple[HotelStay, ...]:
    """只恢复本轮、当前条件下服务端核对过的选择，下一轮不强制旧选择。"""
    selection = (row.request_details or {}).get("selected_hotels")
    if (
        not isinstance(selection, dict)
        or selection.get("run_id") != str(context.run_id)
        or selection.get("revision") != revision
    ):
        return ()
    return TypeAdapter(tuple[HotelStay, ...]).validate_python(selection["stays"])
