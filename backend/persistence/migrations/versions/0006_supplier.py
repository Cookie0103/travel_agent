"""供应商独立hold/订单事实；client_ref是跨进程稳定幂等键。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supplier_holds",
        sa.Column("client_ref", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("client_ref", name="pk_supplier_holds"),
        sa.UniqueConstraint("id", name="uq_supplier_holds_id"),
    )
    op.create_table(
        "supplier_orders",
        sa.Column("client_ref", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["client_ref"],
            ["supplier_holds.client_ref"],
            name="fk_supplier_orders_client_ref_supplier_holds",
        ),
        sa.PrimaryKeyConstraint("client_ref", name="pk_supplier_orders"),
        sa.UniqueConstraint("id", name="uq_supplier_orders_id"),
    )


def downgrade() -> None:
    op.drop_table("supplier_orders")
    op.drop_table("supplier_holds")
