"""API 的身份/会话用例入口；令牌、事务和数据库错误在这里收敛。"""

import hashlib
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import URL

from backend.persistence import sessions
from backend.persistence.database import Database, configuration, database_url
from backend.services.common import ServiceError, transaction
from backend.services.rate_limit import Clock, RateLimited, SlidingWindow, client_key, positive_int


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
    def __init__(
        self,
        url: URL,
        *,
        demo_enabled: bool = False,
        token_days: int = 30,
        login_per_ip: int = 30,
        login_global: int = 300,
        login_seconds: int = 600,
        clock: Clock = time.monotonic,
    ) -> None:
        self.database = Database(url)
        self.demo_enabled = demo_enabled
        self.token_days = token_days
        # 公网开启演示登录时防止无限建用户；默认值对本地演示宽松。进程内计数，多实例各自计算。
        self.login_ip = SlidingWindow(login_per_ip, login_seconds, clock)
        self.login_all = SlidingWindow(login_global, login_seconds, clock)

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> "SessionService":
        config = configuration(environment)
        try:
            days = int(config["DEMO_TOKEN_DAYS"] or 30)
            if not 1 <= days <= 365:
                raise ValueError
        except ValueError:
            raise ValueError("DEMO_TOKEN_DAYS 必须为1至365的整数") from None
        return cls(
            database_url(config),
            demo_enabled=config["DEMO_MODE"].casefold() == "true",
            token_days=days,
            login_per_ip=positive_int(config, "DEMO_LOGIN_PER_IP", 30, 1000),
            login_global=positive_int(config, "DEMO_LOGIN_GLOBAL", 300, 5000),
            login_seconds=positive_int(config, "DEMO_LOGIN_WINDOW_SECONDS", 600, 86400),
        )

    async def health(self) -> None:
        async with transaction(self.database) as db:
            await sessions.check_connection(db)

    async def ready(self) -> None:
        """存活之外还要求迁移在 head；否则业务请求才会 500。"""
        async with transaction(self.database) as db:
            if not await sessions.is_migrated(db):
                raise ServiceError(503, "unavailable", "数据库迁移未到最新", reason="not_migrated")

    def check_login_rate(self, client: str) -> None:
        """按客户端和全局两道滑动窗口；超限抛RateLimited(429 + Retry-After)。"""
        key = client_key(client)
        # 先检查后提交：任一道拒绝都不留下按IP状态，也不消耗另一道额度。
        wait = self.login_ip.check(key) or self.login_all.check("*")
        if wait:
            raise RateLimited(wait, "demo_login_rate")
        self.login_ip.hit(key)
        self.login_all.hit("*")

    async def create_demo_user(self, request: DemoLogin, client: str | None = None) -> DemoIdentity:
        if not self.demo_enabled:
            raise ServiceError(403, "blocked", "演示登录未启用")
        if client is not None:
            self.check_login_rate(client)
        token = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(days=self.token_days)
        async with transaction(self.database) as db:
            user = await sessions.create_user(
                db, request.display_name, hashlib.sha256(token.encode()).hexdigest(), expires
            )
            return DemoIdentity(user.id, token, expires)

    async def authenticate(self, authorization: str | None) -> UUID:
        if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 256:
            raise ServiceError(401, "blocked", "需要有效身份")
        token_hash = hashlib.sha256(authorization[7:].encode()).hexdigest()
        async with transaction(self.database) as db:
            user = await sessions.find_user(db, token_hash, datetime.now(UTC))
            if user is None:
                raise ServiceError(401, "blocked", "需要有效身份")
            return user.id

    async def new_session(self, user_id: UUID) -> SessionView:
        async with transaction(self.database) as db:
            row = await sessions.create_session(db, user_id)
            return SessionView(row.id, row.created_at)

    async def get_session(self, user_id: UUID, session_id: UUID) -> SessionView:
        async with transaction(self.database) as db:
            row = await sessions.get_session(db, user_id, session_id)
            if row is None:
                raise ServiceError(404, "blocked", "会话不存在")
            return SessionView(row.id, row.created_at)

    async def close(self) -> None:
        await self.database.close()
