"""酒店展示细节单独保存，旧报价和预订快照保持旧形状。"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE evidence ADD COLUMN IF NOT EXISTS display_details JSONB")


def downgrade() -> None:
    # 回退旧代码时保留已经收到的供应商链接；再次升级不删除或覆写。
    pass
