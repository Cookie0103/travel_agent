"""实时API调用计数与允许缓存的Google坐标。"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_api_usage",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("api", sa.String(20), primary_key=True),
        sa.Column("calls", sa.Integer(), nullable=False),
    )
    op.create_table(
        "google_coordinates",
        sa.Column("query", sa.String(200), primary_key=True),
        sa.Column("place_id", sa.String(150), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("google_coordinates")
    op.drop_table("external_api_usage")
