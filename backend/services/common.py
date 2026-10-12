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


def database_failure_reason(error: BaseException) -> str:
    """连接故障可能没有SQLSTATE；只记录白名单原因，不输出原异常或连接串。"""
    original = getattr(error.__context__, "orig", None) or getattr(error, "orig", error)
    message = str(original).casefold()
    for reason, markers in (
        ("connection_timeout", ("timeout expired", "connection timed out")),
        ("connection_refused", ("connection refused",)),
        ("connection_closed", ("server closed the connection", "connection reset")),
        ("authentication_failed", ("password authentication failed",)),
        ("connection_limit", ("too many clients", "too many connections")),
    ):
        if any(marker in message for marker in markers):
            return reason
    return "unknown"


class ServiceError(RuntimeError):
    def __init__(
        self,
        status: int,
        code: ErrorCode,
        message: str,
        reason: str = "",
        fields: tuple[str, ...] = (),
    ) -> None:
        # reason是仅供TRACE的固定英文标签(不含用户/第三方文本)；message可能含插值，不进日志。
        # fields是缺失条件的封闭字段名，供工具层转成missing:<字段>标签。
        self.status, self.code, self.reason, self.fields = status, code, reason, fields
        super().__init__(message)


@asynccontextmanager
async def transaction(database: Database) -> AsyncIterator[AsyncSession]:
    try:
        async with database.sessions.begin() as db:
            yield db
    except (SQLAlchemyError, OSError) as error:
        kind, sqlstate = database_error_details(error)
        LOGGER.error(
            "Database transaction failed: error=%s sqlstate=%s reason=%s",
            kind,
            sqlstate,
            database_failure_reason(error),
        )
        raise ServiceError(503, "unavailable", "数据库暂不可用") from None
