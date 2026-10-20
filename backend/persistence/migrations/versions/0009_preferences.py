"""偏好值及删除后保留的版本同用户行锁提交。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("preference_revision", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "users", sa.Column("preferences", postgresql.JSONB(), server_default="{}", nullable=False)
    )
    op.alter_column("users", "preference_revision", server_default=None)
    op.alter_column("users", "preferences", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "preferences")
    op.drop_column("users", "preference_revision")
