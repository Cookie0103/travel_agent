"""只读旅行摘要与轮次恢复用例；认证来自API，分页不重放工具或模型。"""

import base64
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from backend.domain.travel_request import TravelRequest
from backend.persistence import history, runs, sessions
from backend.persistence.database import Database
from backend.services.common import ServiceError, transaction
from backend.services.runs import RunView, view


def boundary(cursor: str | None) -> history.Boundary | None:
    if cursor is None:
        return None
    try:
        if not 1 <= len(cursor) <= 256 or re.fullmatch(r"[A-Za-z0-9_-]+", cursor) is None:
            raise ValueError
        data = json.loads(
            base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        )
        if not isinstance(data, list) or len(data) != 3 or type(data[0]) is not int or data[0] != 1:
            raise ValueError
        if not isinstance(data[1], str) or not isinstance(data[2], str):
            raise ValueError
        stamp, key = datetime.fromisoformat(data[1]), UUID(data[2])
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError
        return stamp, key
    except (ValueError, UnicodeError):
        raise ServiceError(422, "blocked", "分页游标无效") from None


def cursor(stamp: datetime, key: UUID) -> str:
    data = json.dumps([1, stamp.astimezone(UTC).isoformat(), str(key)], separators=(",", ":"))
    return base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")


@dataclass(frozen=True)
class SessionSummary:
    session_id: UUID
    created_at: datetime
    city: str | None
    start_date: date | None
    end_date: date | None
    plan_id: UUID | None
    current_version: int | None
    last_activity_at: datetime


@dataclass(frozen=True)
class SessionPage:
    items: tuple[SessionSummary, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class HistoricalRun(RunView):
    prompt: str = ""
    draft_id: UUID | None = None


@dataclass(frozen=True)
class RunPage:
    items: tuple[HistoricalRun, ...]
    next_before: str | None


def summary(row: history.SessionHistoryRow) -> SessionSummary:
    request = TravelRequest.model_validate(row.conditions or {})
    times = [row.session.created_at]
    if row.run_activity is not None:
        times.append(row.run_activity)
    if row.saved_at is not None:
        times.append(datetime.fromisoformat(row.saved_at))
    return SessionSummary(
        row.session.id,
        row.session.created_at,
        request.city,
        request.start_date,
        request.end_date,
        row.plan_id,
        row.current_version,
        max(times),
    )


def draft_id(events: tuple[dict[str, object], ...]) -> UUID | None:
    for event in reversed(events):
        presentation = event.get("presentation")
        data = presentation.get("data") if isinstance(presentation, dict) else None
        value = data.get("draft_id") if isinstance(data, dict) else None
        if isinstance(value, str):
            try:
                return UUID(value)
            except ValueError:
                continue
    return None


class HistoryService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def sessions(self, user_id: UUID, limit: int, after: str | None) -> SessionPage:
        before = boundary(after)
        async with transaction(self.database) as db:
            rows = await history.session_page(db, user_id, limit, before)
            page = rows[:limit]
            next_cursor = (
                cursor(page[-1].session.created_at, page[-1].session.id)
                if len(rows) > limit
                else None
            )
            return SessionPage(tuple(summary(row) for row in page), next_cursor)

    async def runs(self, user_id: UUID, session_id: UUID, limit: int, after: str | None) -> RunPage:
        before = boundary(after)
        async with transaction(self.database) as db:
            if await sessions.get_session(db, user_id, session_id) is None:
                raise ServiceError(404, "blocked", "会话不存在")
            rows = await history.run_page(db, user_id, session_id, limit, before)
            page = rows[:limit]
            next_before = cursor(page[-1].created_at, page[-1].id) if len(rows) > limit else None
            items = []
            for row in reversed(page):
                current = view(row)
                events = await runs.presentations(db, row.id)
                items.append(
                    HistoricalRun(
                        current.run_id,
                        current.session_id,
                        current.status,
                        current.mode,
                        current.answer,
                        current.error_code,
                        current.last_sequence,
                        current.created_at,
                        events,
                        row.prompt,
                        draft_id(events),
                    )
                )
            return RunPage(tuple(items), next_before)
