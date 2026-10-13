"""用户显式触发一次画像生成；模型无工具，只读取active长期事实。"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.domain.preferences import PreferenceVersion
from backend.domain.user_profile import ProfileGeneration, UserProfileView, supported_profile
from backend.limits import ProbeError
from backend.persistence import memory, sessions
from backend.persistence.database import Database
from backend.persistence.models import UserProfileSummaryRow
from backend.services.common import ServiceError, transaction

ROOT = Path(__file__).resolve().parents[2]
__all__ = ["UserProfileService", "UserProfileView"]


class UserProfileService:
    def __init__(self, database: Database, *, live_enabled: bool = False) -> None:
        self.database, self.live_enabled = database, live_enabled

    async def get(self, user_id: UUID) -> UserProfileView:
        async with transaction(self.database) as db:
            return await self.snapshot(db, user_id, can_update=self.live_enabled)

    @staticmethod
    async def snapshot(
        db: AsyncSession, user_id: UUID, *, can_update: bool = False
    ) -> UserProfileView:
        row = await db.get(UserProfileSummaryRow, user_id)
        user = await sessions.get_user(db, user_id)
        if user is None:
            raise ServiceError(404, "blocked", "用户不存在")
        facts = await memory.active(db, user_id)
        active = {str(f.id) for f in facts}
        if (
            row is None
            or row.invalidated_at is not None
            or row.preference_revision != user.preference_revision
            or not row.text
            or not row.cited_fact_ids
            or not set(row.cited_fact_ids) <= active
        ):
            return UserProfileView(can_update=can_update)
        return UserProfileView(
            text=row.text,
            cited_fact_ids=tuple(UUID(value) for value in row.cited_fact_ids),
            created_at=row.created_at,
            can_update=can_update,
        )

    async def generate(self, user_id: UUID, version: PreferenceVersion) -> UserProfileView:
        from backend.providers.claude_agent.structured import structured_call

        if not self.live_enabled:
            raise ServiceError(403, "blocked", "画像更新需要启用已授权的DeepSeek模式")
        async with transaction(self.database) as db:
            user = await sessions.get_user(db, user_id, lock=True)
            if user is None:
                raise ServiceError(404, "blocked", "用户不存在")
            if user.preference_revision != version.expected_revision:
                raise ServiceError(409, "conflict", "偏好已变化，请读取最新版本")
            facts = await memory.active(db, user_id)
            # 不把其他会话的trip事实提升为用户级长期画像；与memory快照相同上限。
            data = memory.bounded_snapshot(facts)
        if not data:
            return UserProfileView(can_update=True)
        try:
            response, _ = await asyncio.to_thread(
                structured_call, "profile", {"active_facts": data}, ROOT
            )
            output = ProfileGeneration.model_validate_json(response)
        except (ProbeError, ValueError):
            raise ServiceError(
                503, "unavailable", "画像生成未完成，偏好事实仍保留，请稍后再试"
            ) from None
        text, ids = supported_profile(output, {UUID(str(f["fact_id"])) for f in data})
        if not text:
            raise ServiceError(422, "validation", "画像没有可核验的有效引用，未保存")
        async with transaction(self.database) as db:
            user = await sessions.get_user(db, user_id, lock=True)
            if user is None or user.preference_revision != version.expected_revision:
                raise ServiceError(409, "conflict", "生成期间偏好已变化，画像未保存，请重新更新")
            active = {f.id for f in await memory.active(db, user_id)}
            if not set(ids) <= active:
                raise ServiceError(409, "conflict", "引用事实已失效，画像未保存")
            row = await db.get(UserProfileSummaryRow, user_id)
            if row is None:
                row = UserProfileSummaryRow(user_id=user_id)
                db.add(row)
            row.text, row.cited_fact_ids = text, [str(f) for f in ids]
            row.preference_revision = version.expected_revision
            row.created_at, row.invalidated_at = datetime.now(UTC), None
        return await self.get(user_id)
