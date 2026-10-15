"""M1.3：带版本的旅行条件与按用户/会话隔离的事实证据。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "travel_requests",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("conditions", postgresql.JSONB(), nullable=False),
        sa.Column("source_turn_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name="fk_travel_requests_session_id_sessions"
        ),
        sa.PrimaryKeyConstraint("session_id", name="pk_travel_requests"),
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("invalidated", sa.Boolean(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_evidence_user_id_users"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name="fk_evidence_session_id_sessions"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence"),
    )
    op.create_index("ix_evidence_session_id", "evidence", ["session_id"])


def downgrade() -> None:
    op.drop_table("evidence")
    op.drop_table("travel_requests")
