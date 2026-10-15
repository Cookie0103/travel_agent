"""真实目录查询及证据发布；复用领域搜索，结果交给工具/MCP，不在线抓取。"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from backend.domain.catalog import Article as Article
from backend.domain.catalog import ContentSearchInput, Place, PlaceSearchInput, search
from backend.domain.evidence import EvidenceKind, EvidenceRecord, evidence_conditions
from backend.domain.execution import RunContext
from backend.domain.external_data import ExternalDataError
from backend.domain.travel_request import TravelRequest
from backend.persistence.catalog import load_catalog
from backend.services.common import ServiceError, transaction
from backend.services.travel import TravelService


@dataclass(frozen=True)
class CatalogResult:
    collection: str
    rows: list[dict[str, object]]
    evidence: tuple[EvidenceRecord, ...]
    warnings: tuple[str, ...] = ()


class CatalogService:
    def __init__(self, travel: TravelService) -> None:
        self.travel = travel

    async def articles(self) -> tuple[Article, ...]:
        """公开攻略只读；不创建业务身份、Evidence、任务或模型请求。"""
        data = await self._catalog()
        return tuple(Article.model_validate(row) for row in data["articles"])

    async def article(self, article_id: str) -> Article:
        articles = await self.articles()
        result = next((entry for entry in articles if entry.article_id == article_id), None)
        if result is None:
            raise ServiceError(404, "blocked", "攻略ID不存在")
        return result

    async def query(self, context: RunContext, arguments: ContentSearchInput) -> CatalogResult:
        current, data = await self._load(context)
        collection = "places" if isinstance(arguments, PlaceSearchInput) else "articles"
        if collection == "places" and self.travel.live:
            google = self.travel.live.google
            if not google:
                raise ServiceError(503, "unavailable", "未配置 GOOGLE_MAPS_API_KEY")
            try:
                places = await google.search_places(
                    arguments.city, arguments.query, arguments.limit
                )
                rows = [place.model_dump(mode="json") for place in places]
                result = await self._publish(context, current, collection, rows)
                point = google.points.get(arguments.city)
                return CatalogResult(
                    result.collection,
                    result.rows,
                    result.evidence,
                    ("目的地范围较大，请让用户指定具体城市或区域",)
                    if point and point.broad
                    else (),
                )
            except ExternalDataError as error:
                if error.validation:
                    raise ServiceError(422, "validation", str(error)) from None
                result = await self._publish(
                    context, current, collection, search(data[collection], arguments)
                )
                return CatalogResult(
                    result.collection,
                    result.rows,
                    result.evidence,
                    (str(error), "实时查询失败，以下仅为历史快照结果"),
                )
        return await self._publish(
            context, current, collection, search(data[collection], arguments)
        )

    async def get(self, context: RunContext, collection: str, entity_id: str) -> CatalogResult:
        current, data = await self._load(context)
        if collection == "places" and entity_id.startswith("gplace:") and self.travel.live:
            if not self.travel.live.google:
                raise ServiceError(503, "unavailable", "未配置 GOOGLE_MAPS_API_KEY")
            try:
                place = await self.travel.live.google.details(entity_id, current.city or "")
            except ExternalDataError as error:
                raise ServiceError(503, "unavailable", str(error)) from None
            return await self._publish(
                context, current, collection, [place.model_dump(mode="json")]
            )
        key = "place_id" if collection == "places" else "article_id"
        rows = [row for row in data[collection] if row.get(key) == entity_id]
        if not rows:
            raise ServiceError(404, "blocked", "地点或攻略ID不存在")
        return await self._publish(context, current, collection, rows)

    async def _load(
        self, context: RunContext
    ) -> tuple[TravelRequest, dict[str, list[dict[str, object]]]]:
        current = await self.travel.get_request(context)
        return current, await self._catalog()

    async def _catalog(self) -> dict[str, list[dict[str, object]]]:
        async with transaction(self.travel.database) as db:
            data = await load_catalog(db)
        if not any(data.values()):
            raise ServiceError(503, "unavailable", "目录尚未导入，请运行data.import_catalog")
        return data

    async def _publish(
        self,
        context: RunContext,
        current: TravelRequest,
        collection: str,
        rows: list[dict[str, object]],
    ) -> CatalogResult:
        kind: EvidenceKind = "place" if collection == "places" else "article"
        records: list[EvidenceRecord] = []
        for row in rows:
            entry = Place.model_validate(row) if kind == "place" else Article.model_validate(row)
            key = entry.place_id if isinstance(entry, Place) else entry.article_id
            now = datetime.now(UTC)
            records.append(
                EvidenceRecord.model_validate(
                    {
                        "entity_id": key,
                        "field_path": "catalog",
                        "value": row,
                        "kind": kind,
                        "request_revision": current.revision,
                        "conditions": evidence_conditions(current, kind),
                        "provider": entry.source.provider,
                        "source_ref": entry.source.source_ref,
                        "content_version": entry.source.content_version,
                        "retrieved_at": now,
                        "valid_until": now + timedelta(hours=24),
                        "data_mode": entry.source.data_mode,
                    }
                )
            )
        if records:
            await self.travel.record_evidence(context, records)
        return CatalogResult(collection, rows, tuple(records))
