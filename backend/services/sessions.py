"""API 的身份/会话用例入口；令牌、事务和数据库错误在这里收敛。"""

import hashlib
import secrets
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.execution import ErrorCode
from backend.persistence import sessions
from backend.persistence.database import Database, configuration, database_url


class ServiceError(RuntimeError):
    def __init__(self, status: int, code: ErrorCode, message: str) -> None:
        self.status, self.code = status, code
        super().__init__(message)


class DemoLogin(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)
    display_name: str = Field(default="旅行者", min_length=1, max_length=60)


@dataclass(frozen=True)
class DemoIdentity:
    user_id: UUID
    token: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class SessionView:
    session_id: UUID
    created_at: datetime


class SessionService:
    def __init__(self, url: URL, *, demo_enabled: bool = False) -> None:
        self.database = Database(url)
        self.demo_enabled = demo_enabled

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> "SessionService":
        config = configuration(environment)
        return cls(database_url(config), demo_enabled=config["DEMO_MODE"].casefold() == "true")

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[AsyncSession]:
        try:
            async with self.database.sessions.begin() as db:
                yield db
        except (SQLAlchemyError, OSError):
            raise ServiceError(503, "unavailable", "数据库暂不可用") from None

    async def health(self) -> None:
        async with self._transaction() as db:
            await sessions.check_connection(db)

    async def create_demo_user(self, request: DemoLogin) -> DemoIdentity:
        if not self.demo_enabled:
            raise ServiceError(403, "blocked", "演示登录未启用")
        token = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(hours=24)
        async with self._transaction() as db:
            user = await sessions.create_user(
                db, request.display_name, hashlib.sha256(token.encode()).hexdigest(), expires
            )
            return DemoIdentity(user.id, token, expires)

    async def authenticate(self, authorization: str | None) -> UUID:
        if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 256:
            raise ServiceError(401, "blocked", "需要有效身份")
        token_hash = hashlib.sha256(authorization[7:].encode()).hexdigest()
        async with self._transaction() as db:
            user = await sessions.find_user(db, token_hash, datetime.now(UTC))
            if user is None:
                raise ServiceError(401, "blocked", "需要有效身份")
            return user.id

    async def new_session(self, user_id: UUID) -> SessionView:
        async with self._transaction() as db:
            row = await sessions.create_session(db, user_id)
            return SessionView(row.id, row.created_at)

    async def get_session(self, user_id: UUID, session_id: UUID) -> SessionView:
        async with self._transaction() as db:
            row = await sessions.get_session(db, user_id, session_id)
            if row is None:
                raise ServiceError(404, "blocked", "会话不存在")
            return SessionView(row.id, row.created_at)

    async def close(self) -> None:
        await self.database.close()
