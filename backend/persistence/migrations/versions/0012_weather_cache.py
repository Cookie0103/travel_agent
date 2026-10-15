"""Open-Meteo 城市/日期范围三小时缓存，跨 SDK 子进程复用。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weather_forecasts",
        sa.Column("city", sa.String(40), primary_key=True),
        sa.Column("start_date", sa.Date(), primary_key=True),
        sa.Column("end_date", sa.Date(), primary_key=True),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("weather_forecasts")
