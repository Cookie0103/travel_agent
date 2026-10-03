"""业务服务共用的事务与安全错误边界；不重复包装每个SQL操作。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.execution import ErrorCode
from backend.persistence.database import Database


class ServiceError(RuntimeError):
    def __init__(self, status: int, code: ErrorCode, message: str) -> None:
        self.status, self.code = status, code
        super().__init__(message)


@asynccontextmanager
async def transaction(database: Database) -> AsyncIterator[AsyncSession]:
    try:
        async with database.sessions.begin() as db:
            yield db
    except (SQLAlchemyError, OSError):
        raise ServiceError(503, "unavailable", "数据库暂不可用") from None
