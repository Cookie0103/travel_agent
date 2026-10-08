"""业务表映射；身份/会话与公开快照独立存储，不把SDK transcript当数据库。"""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, MetaData, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class ExternalApiUsageRow(Base):
    __tablename__ = "external_api_usage"
    day: Mapped[date] = mapped_column(primary_key=True)
    api: Mapped[str] = mapped_column(String(20), primary_key=True)
    calls: Mapped[int]


class GoogleCoordinateRow(Base):
    __tablename__ = "google_coordinates"
    query: Mapped[str] = mapped_column(String(200), primary_key=True)
    place_id: Mapped[str] = mapped_column(String(150))
    latitude: Mapped[float]
    longitude: Mapped[float]
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WeatherForecastRow(Base):
    __tablename__ = "weather_forecasts"
    city: Mapped[str] = mapped_column(String(40), primary_key=True)
    start_date: Mapped[date] = mapped_column(primary_key=True)
    end_date: Mapped[date] = mapped_column(primary_key=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    display_name: Mapped[str] = mapped_column(String(60))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    preference_revision: Mapped[int] = mapped_column(default=0)
    preferences: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    preference_deleted: Mapped[bool] = mapped_column(default=False)
    preference_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogRow(Base):
    """小规模只读目录；payload由Place/Article契约验证，保留来源与版本。"""

    __tablename__ = "catalog_entries"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))
    city: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)


class TravelRequestRow(Base):
    __tablename__ = "travel_requests"

    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(default=0)
    conditions: Mapped[dict[str, object]] = mapped_column(JSONB)
    request_details: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    source_turn_id: Mapped[UUID | None]


class EvidenceRow(Base):
    __tablename__ = "evidence"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    invalidated: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    display_details: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)


class TaskRunRow(Base):
    __tablename__ = "task_runs"
    __table_args__ = (UniqueConstraint("session_id", "client_message_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id"), index=True)
    client_message_id: Mapped[UUID]
    mode: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="running")
    prompt: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")
    error_code: Mapped[str | None] = mapped_column(String(30))
    last_sequence: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunEventRow(Base):
    __tablename__ = "run_events"

    run_id: Mapped[UUID] = mapped_column(ForeignKey("task_runs.id"), primary_key=True)
    sequence: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)


class PlanRow(Base):
    __tablename__ = "plans"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id"), unique=True)
    current_version: Mapped[int] = mapped_column(default=0)


class PlanVersionRow(Base):
    __tablename__ = "plan_versions"

    plan_id: Mapped[UUID] = mapped_column(ForeignKey("plans.id"), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)


class PlanDraftRow(Base):
    __tablename__ = "plan_drafts"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("plans.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id"), index=True)
    confirmed_version: Mapped[int | None]
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)


class SupplierHoldRow(Base):
    """模拟供应商自己的事实，不依赖应用用户/报价证据表。"""

    __tablename__ = "supplier_holds"
    client_ref: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[UUID] = mapped_column(unique=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SupplierOrderRow(Base):
    __tablename__ = "supplier_orders"
    client_ref: Mapped[UUID] = mapped_column(
        ForeignKey("supplier_holds.client_ref"), primary_key=True
    )
    id: Mapped[UUID] = mapped_column(unique=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)


class BookingRow(Base):
    __tablename__ = "bookings"
    __table_args__ = (UniqueConstraint("session_id", "evidence_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id"), index=True)
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey("evidence.id"))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)


class BusinessOperationRow(Base):
    """与业务写入同事务的结果凭据，不依赖SDK tool_call_id。"""

    __tablename__ = "business_operations"
    session_id: Mapped[UUID] = mapped_column(ForeignKey("sessions.id"), primary_key=True)
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)
