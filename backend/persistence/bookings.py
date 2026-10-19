"""预订所有者过滤与同报价幂等SQL；写入由服务统一持有会话锁。"""

from uuid import UUID

from sqlalchemy import DateTime, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.persistence.models import BookingRow


async def owned(db: AsyncSession, user_id: UUID, booking_id: UUID) -> BookingRow | None:
    return await db.scalar(
        select(BookingRow).where(
            BookingRow.id == booking_id,
            BookingRow.user_id == user_id,
        )
    )


async def for_quote(db: AsyncSession, session_id: UUID, evidence_id: UUID) -> BookingRow | None:
    return await db.scalar(
        select(BookingRow).where(
            BookingRow.session_id == session_id,
            BookingRow.evidence_id == evidence_id,
        )
    )


async def for_session(db: AsyncSession, user_id: UUID, session_id: UUID) -> list[BookingRow]:
    return list(
        await db.scalars(
            select(BookingRow)
            .where(
                BookingRow.session_id == session_id,
                BookingRow.user_id == user_id,
            )
            # 恢复入口返回全部预订，不能按随机UUID截断并隐藏活动记录。
            # 按真实时间排序：微秒为0时JSON文本缺少小数部分，文本序不等于时间序。
            .order_by(
                cast(BookingRow.payload["history"][0]["at"].astext, DateTime(timezone=True)).desc(),
                BookingRow.id,
            )
        )
    )
