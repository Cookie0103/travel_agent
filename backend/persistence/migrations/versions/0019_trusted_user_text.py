"""单独保留可信用户输入，生成的选择说明不能作为记忆引用来源。"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 旧prompt可能含生成后缀，不反推/回填成用户原话。
    op.add_column("task_runs", sa.Column("user_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("task_runs", "user_text")
