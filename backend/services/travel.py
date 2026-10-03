"""旅行条件/证据用例；API与旅行工具共用所有者、版本、时效和事务规则。"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError

from backend.domain.evidence import EvidenceRecord
from backend.domain.execution import RunContext
from backend.domain.travel_request import (
    RequestConflict,
    RequestPatch,
    TravelRequest,
    apply_request_patch,
    invalidated_kinds,
)
from backend.persistence import travel
from backend.persistence.database import Database
from backend.persistence.models import TravelRequestRow
from backend.services.common import ServiceError, transaction

__all__ = ["RunContext", "RequestPatch", "TravelRequest", "RequestUpdate", "TravelService"]


def _request(row: TravelRequestRow | None) -> TravelRequest:
    if row is None:
        raise ServiceError(404, "blocked", "会话不存在")
    return TravelRequest.model_validate({**row.conditions, "revision": row.revision})


@dataclass(frozen=True)
class RequestUpdate:
    request: TravelRequest
    changed_fields: tuple[str, ...]


class TravelService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get_request(self, context: RunContext) -> TravelRequest:
        async with transaction(self.database) as db:
            return _request(await travel.owned_request(db, context))

    async def patch_request(self, context: RunContext, patch: RequestPatch) -> RequestUpdate:
        async with transaction(self.database) as db:
            row = await travel.owned_request(db, context)
            current = _request(row)
            assert row is not None
            try:
                updated, changed = apply_request_patch(current, patch)
            except RequestConflict as error:
                raise ServiceError(409, "conflict", str(error)) from None
            except ValidationError:
                raise ServiceError(422, "validation", "合并后的旅行条件无效") from None
            if changed:
                await travel.update_request(
                    db, row, updated, invalidated_kinds(changed), context.run_id
                )
            return RequestUpdate(updated, tuple(sorted(changed)))

    async def record_evidence(self, context: RunContext, records: Sequence[EvidenceRecord]) -> None:
        async with transaction(self.database) as db:
            current = _request(await travel.owned_request(db, context))
            if any(not record.applicable(current, datetime.now(UTC)) for record in records):
                raise ServiceError(409, "conflict", "证据与当前条件或有效期不符")
            await travel.add_evidence(db, context, records)

    async def resolve_evidence(
        self, context: RunContext, ids: Sequence[UUID]
    ) -> tuple[EvidenceRecord, ...]:
        if len(ids) > 50:
            raise ServiceError(422, "validation", "一次最多读取50条证据")
        async with transaction(self.database) as db:
            current = _request(await travel.owned_request(db, context))
            rows = {row.id: row for row in await travel.find_evidence(db, context, ids)}
            if set(ids) != rows.keys():
                raise ServiceError(404, "blocked", "证据不存在或不属于当前会话")
            records = tuple(EvidenceRecord.model_validate(rows[key].payload) for key in ids)
            if any(row.invalidated for row in rows.values()) or any(
                not record.applicable(current, datetime.now(UTC)) for record in records
            ):
                raise ServiceError(409, "conflict", "证据已失效，请重新查询")
            return records
