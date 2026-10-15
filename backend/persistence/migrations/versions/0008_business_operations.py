"""写入和稳定业务结果同事务保存。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_operations",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("session_id", "name", "key", name="pk_business_operations"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.id"], name="fk_business_operations_session_id_sessions"
        ),
    )


def downgrade() -> None:
    op.drop_table("business_operations")
