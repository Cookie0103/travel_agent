"""行程草稿与不可变正式版本；每会话一个行程，确认记录指向第一次保存的版本。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_plans_user_id_users"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name="fk_plans_session_id_sessions"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plans"),
        sa.UniqueConstraint("session_id", name="uq_plans_session_id"),
    )
    op.create_table(
        "plan_versions",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], name="fk_plan_versions_plan_id_plans"),
        sa.PrimaryKeyConstraint("plan_id", "version", name="pk_plan_versions"),
    )
    op.create_table(
        "plan_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed_version", sa.Integer(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], name="fk_plan_drafts_plan_id_plans"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_plan_drafts_user_id_users"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name="fk_plan_drafts_session_id_sessions"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_plan_drafts"),
    )
    op.create_index("ix_plan_drafts_session_id", "plan_drafts", ["session_id"])


def downgrade() -> None:
    op.drop_table("plan_drafts")
    op.drop_table("plan_versions")
    op.drop_table("plans")
