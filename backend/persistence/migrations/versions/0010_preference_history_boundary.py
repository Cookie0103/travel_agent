"""显式删除墓碑与业务回顾边界；历史记录保留，仅停止向SDK注入旧对话。"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("preference_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("users", sa.Column("preference_changed_at", sa.DateTime(timezone=True)))
    op.alter_column("users", "preference_deleted", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "preference_changed_at")
    op.drop_column("users", "preference_deleted")
