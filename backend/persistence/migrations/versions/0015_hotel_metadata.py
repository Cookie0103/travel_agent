"""酒店基础元数据分列，保留旧三URL严格读取契约。"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE evidence ADD COLUMN IF NOT EXISTS hotel_metadata JSONB")


def downgrade() -> None:
    # 旧代码不读写此列；保留事实供重新升级读取。
    pass
