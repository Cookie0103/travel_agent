"""用户偏好API用例；认证身份限定所有者，版本与清空在同一事务提交。"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.preferences import (
    PreferencePatch,
    Preferences,
    PreferenceValues,
    PreferenceVersion,
)
from backend.persistence import memory, sessions
from backend.persistence.database import Database
from backend.persistence.models import MemoryFactRow, UserRow
from backend.persistence.user_profile import invalidate as invalidate_profile
from backend.services.common import ServiceError, transaction

__all__ = ["PreferencePatch", "Preferences", "PreferenceVersion", "PreferenceService"]


async def preferences_from_row(db: AsyncSession, row: UserRow | None) -> Preferences:
    if row is None:
        raise ServiceError(404, "blocked", "用户不存在")
    values = await memory.projection(db, row.id)
    return Preferences(**values.model_dump(), revision=row.preference_revision)


class PreferenceService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(self, user_id: UUID) -> Preferences:
        async with transaction(self.database) as db:
            return await preferences_from_row(db, await sessions.get_user(db, user_id))

    async def change(
        self, user_id: UUID, change: PreferencePatch | PreferenceVersion
    ) -> Preferences:
        async with transaction(self.database) as db:
            row = await sessions.get_user(db, user_id, lock=True)
            current = await preferences_from_row(db, row)
            assert row is not None
            if current.revision != change.expected_revision:
                raise ServiceError(409, "conflict", "偏好已变化，请读取最新版本")
            patch = isinstance(change, PreferencePatch)
            if not patch:
                row.memory_forgotten_at = datetime.now(UTC)
                await invalidate_profile(db, user_id)
            data = current.model_dump(exclude={"revision"}) if patch else {}
            if isinstance(change, PreferencePatch):
                data.update(change.set_fields.model_dump(exclude_unset=True))
            values = PreferenceValues.model_validate(data)
            changed = values.model_dump() != current.model_dump(exclude={"revision"})
            changed = changed or (not patch and not row.preference_deleted)
            if not patch:
                remaining = await db.scalar(
                    select(MemoryFactRow.id)
                    .where(
                        MemoryFactRow.user_id == user_id,
                        (MemoryFactRow.status != "deleted")
                        | (MemoryFactRow.value.is_not(None) & (MemoryFactRow.value != JSON.NULL))
                        | (MemoryFactRow.evidence_quote != ""),
                    )
                    .limit(1)
                )
                changed = changed or remaining is not None
            updated = Preferences(**values.model_dump(), revision=current.revision + changed)
            if changed:
                await invalidate_profile(db, user_id)
                # 不变量：新版本不能从旧SDK会话或旧业务回顾重新取回删除前的偏好。
                row.preference_changed_at = datetime.now(UTC)
                row.preference_deleted = not patch
                fields = (
                    {
                        field
                        for field in change.set_fields.model_fields_set
                        if getattr(values, field) != getattr(current, field)
                    }
                    if isinstance(change, PreferencePatch)
                    else {"interests", "soft_constraints", "transport"}
                )
                now = datetime.now(UTC)
                if not patch:
                    # 全部忘记也必须清除pending/rejected/superseded正文，而不只删active投影。
                    fields = {"interests", "soft_constraints", "transport"}
                    for fact in await db.scalars(
                        select(MemoryFactRow).where(MemoryFactRow.user_id == user_id)
                    ):
                        fact.status, fact.value, fact.evidence_quote, fact.invalidated_at = (
                            "deleted",
                            None,
                            "",
                            now,
                        )
                else:
                    for field, key in (
                        ("interests", "interest"),
                        ("soft_constraints", "avoid"),
                        ("transport", "transport"),
                    ):
                        if field not in fields:
                            continue
                        for fact in await db.scalars(
                            select(MemoryFactRow).where(
                                MemoryFactRow.user_id == user_id,
                                MemoryFactRow.scope == "long_term",
                                MemoryFactRow.key == key,
                                MemoryFactRow.status.in_(("active", "proposed")),
                            )
                        ):
                            if fact.status == "proposed":
                                fact.status, fact.value, fact.evidence_quote = "deleted", None, ""
                            else:
                                fact.status = "superseded"
                            fact.invalidated_at = now
                        parts = (
                            ([values.transport] if values.transport else [])
                            if field == "transport"
                            else getattr(values, field)
                        )
                        for ordinal, value in enumerate(parts):
                            db.add(
                                MemoryFactRow(
                                    user_id=user_id,
                                    key=key,
                                    value=value,
                                    scope="long_term",
                                    status="active",
                                    source="manual",
                                    ordinal=ordinal,
                                    valid_from=now,
                                    last_confirmed_at=now,
                                )
                            )
            row.preferences = {}
            row.preference_revision = updated.revision
            return updated
