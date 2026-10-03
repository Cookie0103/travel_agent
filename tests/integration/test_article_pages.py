"""M1.8：公开攻略HTTP读取到工作台；真实PG目录，读操作不创建私人业务状态。"""

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import URL, func, select

from backend.api.app import create_app
from backend.domain.catalog import Article
from backend.persistence.catalog import import_catalog
from backend.persistence.models import EvidenceRow, SessionRow, TaskRunRow, UserRow
from backend.persistence.temporary import temporary_database
from backend.services.catalog import CatalogService
from backend.services.common import ServiceError
from backend.services.sessions import SessionService
from data.import_catalog import load_snapshot

pytestmark = pytest.mark.integration


@pytest.fixture
def article_url(postgres_url: URL) -> Iterator[URL]:
    with temporary_database(postgres_url, "test") as target:
        yield target


def test_public_article_list_detail_preserve_source_and_create_no_private_state(
    article_url: URL,
) -> None:
    sessions = SessionService(article_url, demo_enabled=True)
    expected = {a.article_id: a for a in load_snapshot() if isinstance(a, Article)}

    async def seed_and_counts(seed: bool) -> tuple[int, ...]:
        async with sessions.database.sessions.begin() as db:
            if seed:
                await import_catalog(db, load_snapshot())
            counts = []
            for model in (UserRow, SessionRow, TaskRunRow, EvidenceRow):
                counts.append(int(await db.scalar(select(func.count()).select_from(model)) or 0))
            return tuple(counts)

    with TestClient(
        create_app(sessions), backend_options={"loop_factory": asyncio.SelectorEventLoop}
    ) as client:
        assert client.portal is not None
        before = client.portal.call(seed_and_counts, True)
        result = client.get("/articles")
        assert result.status_code == 200
        assert len(result.json()) == len(expected) == 20
        for row in result.json():
            article = Article.model_validate(row)
            assert article == expected[article.article_id]
            read = client.get("/articles/" + article.article_id)
            assert read.status_code == 200 and read.json() == row
        assert client.get("/articles/missing").status_code == 404
        assert client.get("/articles/" + "x" * 101).status_code == 422
        assert client.portal.call(seed_and_counts, False) == before


def test_article_dependency_failure_returns_safe_recoverable_error(
    article_url: URL, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unavailable(self: CatalogService) -> dict[str, list[dict[str, object]]]:
        raise ServiceError(503, "unavailable", "数据库暂不可用")

    monkeypatch.setattr(CatalogService, "_catalog", unavailable)
    sessions = SessionService(article_url, demo_enabled=True)
    with TestClient(
        create_app(sessions), backend_options={"loop_factory": asyncio.SelectorEventLoop}
    ) as client:
        for path in ("/articles", "/articles/example"):
            response = client.get(path)
            assert response.status_code == 503
            assert response.json() == {"code": "unavailable", "message": "数据库暂不可用"}


def test_unimported_article_catalog_is_not_fabricated(article_url: URL) -> None:
    sessions = SessionService(article_url, demo_enabled=True)
    with TestClient(
        create_app(sessions), backend_options={"loop_factory": asyncio.SelectorEventLoop}
    ) as client:
        assert client.get("/articles").status_code == 503
        assert client.get("/articles/missing").status_code == 503
