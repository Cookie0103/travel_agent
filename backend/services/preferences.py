"""用户偏好API用例；认证身份限定所有者，版本与清空在同一事务提交。"""

from datetime import UTC, datetime
from uuid import UUID

from backend.domain.preferences import (
    PreferencePatch,
    Preferences,
    PreferenceValues,
    PreferenceVersion,
)
from backend.persistence import sessions
from backend.persistence.database import Database
from backend.persistence.models import UserRow
from backend.services.common import ServiceError, transaction

__all__ = ["PreferencePatch", "Preferences", "PreferenceVersion", "PreferenceService"]


def preferences_from_row(row: UserRow | None) -> Preferences:
    if row is None:
        raise ServiceError(404, "blocked", "用户不存在")
    return Preferences.model_validate({**row.preferences, "revision": row.preference_revision})


class PreferenceService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(self, user_id: UUID) -> Preferences:
        async with transaction(self.database) as db:
            return preferences_from_row(await sessions.get_user(db, user_id))

    async def change(
        self, user_id: UUID, change: PreferencePatch | PreferenceVersion
    ) -> Preferences:
        async with transaction(self.database) as db:
            row = await sessions.get_user(db, user_id, lock=True)
            current = preferences_from_row(row)
            assert row is not None
            if current.revision != change.expected_revision:
                raise ServiceError(409, "conflict", "偏好已变化，请读取最新版本")
            patch = isinstance(change, PreferencePatch)
            data = current.model_dump(exclude={"revision"}) if patch else {}
            if isinstance(change, PreferencePatch):
                data.update(change.set_fields.model_dump(exclude_unset=True))
            values = PreferenceValues.model_validate(data)
            changed = values.model_dump() != current.model_dump(exclude={"revision"})
            changed = changed or (not patch and not row.preference_deleted)
            updated = Preferences(**values.model_dump(), revision=current.revision + changed)
            if changed:
                # 不变量：新版本不能从旧SDK会话或旧业务回顾重新取回删除前的偏好。
                row.preference_changed_at = datetime.now(UTC)
                row.preference_deleted = not patch
            row.preferences = values.model_dump(mode="json")
            row.preference_revision = updated.revision
            return updated
