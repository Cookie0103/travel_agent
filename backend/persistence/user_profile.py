"""衍生画像同事务作废并清正文，不能让旧生成结果覆盖遗忘。"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.persistence.models import UserProfileSummaryRow


async def invalidate(db: AsyncSession, user_id: UUID) -> None:
    row = await db.get(UserProfileSummaryRow, user_id)
    if row is not None:
        row.text, row.cited_fact_ids = "", []
        row.invalidated_at = datetime.now(UTC)
