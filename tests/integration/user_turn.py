"""给工具调用一个带可信用户原话的执行记录（explicit_fields 的出处核对读它）。"""

from dataclasses import replace
from uuid import uuid4

from backend.domain.execution import RunContext
from backend.persistence import runs
from backend.services.common import transaction
from backend.services.travel import TravelService


async def start_turn(travel: TravelService, context: RunContext, user_text: str) -> RunContext:
    async with transaction(travel.database) as db:
        row = await runs.create(
            db, context.user_id, context.session_id, uuid4(), user_text, "deepseek"
        )
    return replace(context, run_id=row.id)
