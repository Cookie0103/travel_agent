"""C2：数据库输入类错误(DataError)返回422，其余故障仍是503；日志不含正文。"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from psycopg.errors import InvalidTextRepresentation
from sqlalchemy.exc import DataError, IntegrityError, OperationalError

from backend.persistence.database import Database
from backend.services.common import ServiceError, transaction

SECRET = "秘密正文-do-not-log"


def failing(error: Exception) -> Database:
    @asynccontextmanager
    async def begin() -> AsyncIterator[None]:
        raise error
        yield

    return cast(Database, SimpleNamespace(sessions=SimpleNamespace(begin=begin)))


async def run(error: Exception) -> ServiceError:
    with pytest.raises(ServiceError) as caught:
        async with transaction(failing(error)):
            pass
    return caught.value


@pytest.mark.asyncio
async def test_data_error_is_input_error_not_unavailable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    original = InvalidTextRepresentation(SECRET)
    caplog.set_level(logging.ERROR)
    error = await run(DataError(f"INSERT {SECRET}", {"v": SECRET}, original))
    assert (error.status, error.code) == (422, "validation")
    assert SECRET not in str(error) and SECRET not in caplog.text


@pytest.mark.asyncio
async def test_integrity_and_operational_errors_stay_unavailable() -> None:
    for error in (
        IntegrityError("x", {}, Exception("dup")),
        OperationalError("x", {}, Exception("down")),
    ):
        assert (await run(error)).status == 503
