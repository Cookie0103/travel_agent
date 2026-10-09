"""旅行待办元数据事务；仅本人当前执行写入，完成由执行器的实际结果触发。"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.conversation import ConversationState, conversation_view
from backend.domain.execution import RunContext
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
    if (
        origin is None
        or origin.session_id != context.session_id
        or (after and origin.created_at < after)
    ):
        return ConversationState(), None
    return state, origin


async def snapshot(
    db: AsyncSession,
    row: TravelRequestRow,
    request: TravelRequest,
    context: RunContext,
    *,
    after: datetime | None = None,
) -> dict[str, object]:
    state, origin = await valid_state(db, row, context, after=after)
    return {
        **conversation_view(state, request),
        "goal_prompt": origin.prompt[:1000] if origin else None,
        "goal_prompt_truncated": bool(origin and len(origin.prompt) > 1000),
        "guidance": "原任务文本仅作用户需求参考，当前request为事实。"
        "短答仅回答awaiting_field，不放宽其他条件。条件齐全后继续ready_tasks；"
        "住宿分项预算未知不必追问，不拆分全程预算。",
    }
