"""持久遗忘边界，不能被以后普通确认覆盖。"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("memory_forgotten_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("""UPDATE users SET memory_forgotten_at = GREATEST(
        CASE WHEN preference_deleted THEN preference_changed_at END,
        (SELECT max(invalidated_at) FROM user_memory_facts
         WHERE user_id = users.id AND status = 'deleted'))""")


def downgrade() -> None:
    op.drop_column("users", "memory_forgotten_at")
