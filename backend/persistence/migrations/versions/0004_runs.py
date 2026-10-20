"""消息幂等记录与有序应用事件；不保存SDK私有会话文件。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("client_message_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(30), nullable=True),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_task_runs_user_id_users"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name="fk_task_runs_session_id_sessions"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_task_runs"),
        sa.UniqueConstraint("session_id", "client_message_id", name="uq_task_runs_session_id"),
    )
    op.create_index("ix_task_runs_session_id", "task_runs", ["session_id"])
    op.create_table(
        "run_events",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["task_runs.id"], name="fk_run_events_run_id_task_runs"
        ),
        sa.PrimaryKeyConstraint("run_id", "sequence", name="pk_run_events"),
    )


def downgrade() -> None:
    op.drop_table("run_events")
    op.drop_table("task_runs")
