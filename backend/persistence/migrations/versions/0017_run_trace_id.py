"""新run在消息事务内分配trace锚点；旧记录可为空，不改业务历史。"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task_runs", sa.Column("trace_id", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("task_runs", "trace_id")
