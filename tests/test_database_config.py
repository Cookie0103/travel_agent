"""数据库配置/启动边界：URL编码交SQLAlchemy，Windows服务循环兼容且错误脱敏。"""

import pytest
from sqlalchemy import URL, create_engine
from uvicorn import Config

from backend.persistence.database import database_url
from tests.integration.conftest import isolated_url


def test_postgres_password_with_reserved_characters_round_trips() -> None:
    url = database_url({"POSTGRES_PASSWORD": "test-only:@/word"})
    assert url.password == "test-only:@/word" and url.port == 5434
    assert "test-only" not in repr(url)


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"DATABASE_URL": "invalid-private-value"},
        {"DATABASE_URL": "sqlite:///test.db"},
        {"POSTGRES_PASSWORD": "private", "POSTGRES_PORT": "not-a-port"},
    ],
)
def test_invalid_database_configuration_is_safe(config: dict[str, str]) -> None:
    with pytest.raises(ValueError) as error:
        database_url(config)
    assert "private" not in str(error.value)


def test_uvicorn_custom_loop_factory_returns_an_instance() -> None:
    factory = Config(
        "backend.api.app:create_app", factory=True, loop="backend.server:loop_factory"
    ).get_loop_factory()
    assert factory is not None
    loop = factory()
    try:
        assert not loop.is_running()
    finally:
        loop.close()


def test_test_database_query_cannot_override_local_target() -> None:
    configured = URL.create(
        "postgresql+psycopg",
        host="127.0.0.1",
        port=5434,
        database="development",
        query={
            "dbname": "development",
            "host": "remote",
            "hostaddr": "192.0.2.1",
            "service": "remote",
        },
    )
    target = isolated_url(configured, "travel_agent_test_" + "a" * 32)
    engine = create_engine(target)
    try:
        _, parameters = engine.dialect.create_connect_args(target)
    finally:
        engine.dispose()
    # 方言会添加类型适配 context；只核对连接路由，不限制内部类型适配实现。
    assert parameters["host"] == "127.0.0.1" and parameters["port"] == 5434
    assert parameters["dbname"] == target.database
    assert not {"hostaddr", "service"} & parameters.keys()
    with pytest.raises(ValueError, match="本地"):
        isolated_url(configured.set(host="remote"), "unused")
