"""稳定业务键与结果记录；调用者先核对所有者并持有会话锁。"""

import hashlib
import json
from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.plans import PatchStage, StageInput
from backend.domain.travel_request import RequestPatch
from backend.persistence.models import BusinessOperationRow


def serialize(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date | time):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError("业务键含不支持的契约类型")


def key(arguments: RequestPatch | StageInput) -> str:
    data = arguments.model_dump(mode="python", by_alias=True)
    if isinstance(arguments, RequestPatch):
        # set未写必须保留；clear缺省/空数组与顺序不改变操作含义。
        data["set"] = arguments.set_fields.model_dump(mode="python", exclude_unset=True)
        data["clear"] = sorted(set(arguments.clear))
    elif isinstance(arguments.change, PatchStage):
        change = arguments.change
        data["change"] = {
            "kind": change.kind,
            "plan_id": str(change.plan_id),
            "patch": change.patch.model_dump(
                mode="python",
                exclude={"hotel_evidence_id"}
                if "hotel_evidence_id" not in change.patch.model_fields_set
                else set(),
            ),
        }
    canonical = json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=serialize,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def result(
    db: AsyncSession, session_id: UUID, name: str, key: str
) -> dict[str, object] | None:
    row = await db.get(BusinessOperationRow, (session_id, name, key))
    return row.payload if row else None


def save(
    db: AsyncSession, session_id: UUID, name: str, key: str, result: dict[str, object]
) -> None:
    db.add(BusinessOperationRow(session_id=session_id, name=name, key=key, payload=result))
