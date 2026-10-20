"""选择卡独立按ID锁定，回答与条件/消息同事务提交。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "choice_cards",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("source_run_id", sa.Uuid(), sa.ForeignKey("task_runs.id"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("answered_option_id", sa.String(40)),
        sa.Column("answered_run_id", sa.Uuid(), sa.ForeignKey("task_runs.id")),
        sa.UniqueConstraint("session_id", "id"),
    )
    op.create_index("ix_choice_cards_session_id", "choice_cards", ["session_id"])


def downgrade() -> None:
    op.drop_table("choice_cards")
