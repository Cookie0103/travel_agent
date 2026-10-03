"""业务服务共用的事务与安全错误边界；不重复包装每个SQL操作。"""

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.execution import ErrorCode
from backend.persistence.database import Database

LOGGER = logging.getLogger(__name__)


def database_error_details(error: BaseException) -> tuple[str, str | None]:
    """只返回异常类型和标准SQLSTATE，不格式化原SQL、参数或连接字符串。"""
    original = getattr(error.__context__, "orig", None)
    sqlstate = getattr(original or getattr(error, "orig", None), "sqlstate", None)
    return type(error).__name__, (
        sqlstate if isinstance(sqlstate, str) and re.fullmatch(r"[0-9A-Z]{5}", sqlstate) else None
    )


class ServiceError(RuntimeError):
    def __init__(self, status: int, code: ErrorCode, message: str) -> None:
        self.status, self.code = status, code
        super().__init__(message)


@asynccontextmanager
async def transaction(database: Database) -> AsyncIterator[AsyncSession]:
    try:
        async with database.sessions.begin() as db:
            yield db
    except (SQLAlchemyError, OSError) as error:
        kind, sqlstate = database_error_details(error)
        LOGGER.error("Database transaction failed: error=%s sqlstate=%s", kind, sqlstate)
        raise ServiceError(503, "unavailable", "数据库暂不可用") from None
