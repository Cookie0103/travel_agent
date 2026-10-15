"""所有PG测试复用专用本地库创建/迁移与有界清理，不触碰开发数据。"""

from collections.abc import Iterator

import psycopg
import pytest
from sqlalchemy import URL

from backend.persistence.database import configuration, database_url
from backend.persistence.temporary import isolated_url as isolated_url
from backend.persistence.temporary import temporary_database


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[URL]:
    try:
        with temporary_database(database_url(configuration()), "test") as target:
            yield target
    except psycopg.OperationalError:
        pytest.fail("项目PostgreSQL不可用，请先运行dev db-up；未完成测试库验证", pytrace=False)
