"""用户和会话的数据库操作；所有会话读取都在 SQL 中约束 owner。"""

from datetime import datetime
from functools import cache
from uuid import UUID

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.persistence.database import ROOT
from backend.persistence.models import SessionRow, UserRow


async def check_connection(db: AsyncSession) -> None:
    await db.execute(text("SELECT 1"))


@cache
def migration_head() -> str | None:
    """代码里的 Alembic head；单 head 是迁移一致性测试保证的不变量。"""
    config = Config(str(ROOT / "backend/persistence/alembic.ini"))
    return ScriptDirectory.from_config(config).get_current_head()


async def is_migrated(db: AsyncSession) -> bool:
    """库内 alembic_version 是否等于脚本 head；未迁移的空库返回 False。"""
    if await db.scalar(text("SELECT to_regclass('alembic_version')")) is None:
        return False
    versions = (await db.scalars(text("SELECT version_num FROM alembic_version"))).all()
    return list(versions) == [migration_head()]


async def get_user(db: AsyncSession, user_id: UUID, *, lock: bool = False) -> UserRow | None:
    statement = select(UserRow).where(UserRow.id == user_id)
    return await db.scalar(statement.with_for_update() if lock else statement)


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


async def get_session(
    db: AsyncSession, user_id: UUID, session_id: UUID, *, lock: bool = False
) -> SessionRow | None:
    # 不变量：不能先按ID查出对象再由调用方自觉检查归属。
    statement = select(SessionRow).where(
        SessionRow.id == session_id,
        SessionRow.user_id == user_id,
    )
    return await db.scalar(statement.with_for_update() if lock else statement)
