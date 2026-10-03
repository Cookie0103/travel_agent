"""用户和会话的数据库操作；所有会话读取都在 SQL 中约束 owner。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.persistence.models import SessionRow, UserRow


async def check_connection(db: AsyncSession) -> None:
    await db.execute(text("SELECT 1"))


async def create_user(db: AsyncSession, name: str, token_hash: str, expires: datetime) -> UserRow:
    user = UserRow(display_name=name, token_hash=token_hash, token_expires_at=expires)
    db.add(user)
    await db.flush()
    return user


async def find_user(db: AsyncSession, token_hash: str, now: datetime) -> UserRow | None:
    return await db.scalar(
        select(UserRow).where(
            UserRow.token_hash == token_hash,
            UserRow.token_expires_at > now,
        )
    )


async def create_session(db: AsyncSession, user_id: UUID) -> SessionRow:
    session = SessionRow(user_id=user_id)
    db.add(session)
    await db.flush()
    return session


async def get_session(db: AsyncSession, user_id: UUID, session_id: UUID) -> SessionRow | None:
    # 不变量：不能先按ID查出对象再由调用方自觉检查归属。
    return await db.scalar(
        select(SessionRow).where(
            SessionRow.id == session_id,
            SessionRow.user_id == user_id,
        )
    )
