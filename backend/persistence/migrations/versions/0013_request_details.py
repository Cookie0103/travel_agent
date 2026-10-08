"""住宿分项细节的兼容增量列，旧conditions仍由旧模型读取。"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE travel_requests ADD COLUMN IF NOT EXISTS request_details JSONB")


def downgrade() -> None:
    # 恢复旧代码时保留新预算事实，不删除该列；重升级列也已存在。
    pass
