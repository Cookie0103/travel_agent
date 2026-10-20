"""枚举型列加CHECK，task_runs加(session_id, created_at)索引；只加约束/索引，不改数据。

取值是写迁移时从domain Literal冻结的快照（迁移不得随代码漂移）；
tests/integration/test_schema_constraints.py 断言这些CHECK与当前代码枚举一致。
先查既有数据，有未知取值就报错中止并指出表列，不静默改写；再NOT VALID加约束+VALIDATE
（VALIDATE只取SHARE UPDATE EXCLUSIVE锁）。索引不用CONCURRENTLY：表小，且迁移在事务中。
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

# (表, 约束短名, 被检表达式, 显示用列名, 取值)
CHECKS = (
    (
        "task_runs",
        "status",
        "status",
        "status",
        ("running", "cancelling", "completed", "failed", "cancelled", "partial", "awaiting_user"),
    ),
    # "live"是早期版本写过的历史mode；旧库行仍在，须允许。
    ("task_runs", "mode", "mode", "mode", ("offline", "deepseek", "claude", "live")),
    # travel_details是旧卡仍存在库里的种类（domain.choices.FORM_ROW_KINDS，读取边界归一）。
    (
        "choice_cards",
        "kind",
        "kind",
        "kind",
        ("pace", "form", "budget_relaxation", "memory_confirm", "travel_details"),
    ),
    ("evidence", "kind", "kind", "kind", ("place", "article", "hotel_offer", "route")),
    ("user_memory_facts", "scope", "scope", "scope", ("long_term", "trip")),
    (
        "user_memory_facts",
        "status",
        "status",
        "status",
        ("proposed", "active", "rejected", "superseded", "deleted"),
    ),
    (
        "user_memory_facts",
        "source",
        "source",
        "source",
        ("user_utterance", "manual", "migrated"),
    ),
    (
        "bookings",
        "status",
        "(payload ->> 'status')",
        "payload.status",
        ("quoted", "held", "confirmed", "booked", "failed", "unknown", "expired"),
    ),
    ("catalog_entries", "kind", "kind", "kind", ("places", "articles")),
)


def listed(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    bind = op.get_bind()
    for table, _, expression, label, values in CHECKS:
        unknown = (
            bind.execute(
                sa.text(
                    f"SELECT DISTINCT {expression} AS value FROM {table} "
                    f"WHERE {expression} IS NOT NULL "
                    f"AND {expression} NOT IN ({listed(values)}) LIMIT 5"
                )
            )
            .scalars()
            .all()
        )
        if unknown:
            raise RuntimeError(f"{table}.{label} 含未知取值 {unknown}；请先人工处理再升级")
    for table, name, expression, _, values in CHECKS:
        constraint = f"ck_{table}_{name}"
        if bind.scalar(
            sa.text("SELECT 1 FROM pg_constraint WHERE conname=:name"), {"name": constraint}
        ):
            continue  # 回退实验/重放（stamp后再升级）时约束已在，不重复添加
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
            f"CHECK ({expression} IN ({listed(values)})) NOT VALID"
        )
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {constraint}")
    op.create_index(
        "ix_task_runs_session_id_created_at",
        "task_runs",
        ["session_id", "created_at"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_task_runs_session_id_created_at", table_name="task_runs")
    for table, name, _, _, _ in CHECKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_{name}")
