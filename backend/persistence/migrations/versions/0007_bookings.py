"""应用预订与历史状态；同会话同Evidence只有一个稳定预订ID。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bookings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_bookings"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_bookings_user_id_users"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name="fk_bookings_session_id_sessions"
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"], ["evidence.id"], name="fk_bookings_evidence_id_evidence"
        ),
        sa.UniqueConstraint("session_id", "evidence_id", name="uq_bookings_session_id"),
    )
    op.create_index("ix_bookings_session_id", "bookings", ["session_id"])


def downgrade() -> None:
    op.drop_table("bookings")
