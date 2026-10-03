"""数据库配置和连接工厂；共享同一环境解析，每个业务事务使用独立会话。"""

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[2]
CONFIG_KEYS = (
    "DATABASE_URL",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_PORT",
    "DEMO_MODE",
)


def configuration(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    values = dotenv_values(ROOT / ".env", encoding="utf-8")
    source = os.environ if environment is None else environment
    return {key: source.get(key, values.get(key) or "") for key in CONFIG_KEYS}


def database_url(config: Mapping[str, str]) -> URL:
    try:
        raw = config.get("DATABASE_URL", "").strip()
        url = (
            make_url(raw)
            if raw
            else URL.create(
                "postgresql+psycopg",
                username=config.get("POSTGRES_USER") or "travel_agent",
                password=config.get("POSTGRES_PASSWORD"),
                host="127.0.0.1",
                port=int(config.get("POSTGRES_PORT") or "5434"),
                database=config.get("POSTGRES_DB") or "travel_agent",
            )
        )
        if url.drivername == "postgresql":
            url = url.set(drivername="postgresql+psycopg")
        if (
            url.drivername != "postgresql+psycopg"
            or not url.host
            or not url.database
            or not url.password
        ):
            raise ValueError
        return url
    except (ValueError, TypeError, ArgumentError):
        raise ValueError("数据库配置无效；需要PostgreSQL地址、库名和密码") from None


class Database:
    def __init__(self, url: URL) -> None:
        self.engine = create_async_engine(
            url,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def close(self) -> None:
        await self.engine.dispose()
