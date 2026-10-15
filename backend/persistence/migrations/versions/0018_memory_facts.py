"""偏好JSON迁入有序事实，清除旧正文；保留旧列供从active事实恢复投影。"""

import json
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("user_memory_facts"):
        # 旧代码回退期间可显式编辑兼容列；只调和变更字段，墓碑不复活。
        reconcile_legacy(bind)
        bind.execute(sa.text("UPDATE users SET preferences='{}'::jsonb"))
        return
    op.create_table(
        "user_memory_facts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key", sa.String(30), nullable=False),
        sa.Column("value", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("scope", sa.String(10), nullable=False),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("source_run_id", sa.Uuid(), sa.ForeignKey("task_runs.id"), nullable=True),
        sa.Column("evidence_quote", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by", sa.Uuid(), sa.ForeignKey("user_memory_facts.id"), nullable=True),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_user_memory_facts_user_status_key", "user_memory_facts", ["user_id", "status", "key"]
    )
    bind = op.get_bind()
    for row in bind.execute(sa.text("SELECT id,preferences FROM users")):
        values = row.preferences or {}
        for field, key in (
            ("interests", "interest"),
            ("soft_constraints", "avoid"),
            ("transport", "transport"),
        ):
            parts = (
                ([values[field]] if values.get(field) else [])
                if field == "transport"
                else values.get(field, [])
            )
            for ordinal, value in enumerate(parts):
                bind.execute(
                    sa.text(
                        "INSERT INTO user_memory_facts(id,user_id,key,value,scope,status,source,"
                        "evidence_quote,ordinal,valid_from,last_confirmed_at) "
                        "VALUES (:id,:user,:key,CAST(:value AS jsonb),'long_term','active',"
                        "'migrated','',:ordinal,now(),now())"
                    ),
                    {
                        "id": uuid4(),
                        "user": row.id,
                        "key": key,
                        "value": json.dumps(value, ensure_ascii=False),
                        "ordinal": ordinal,
                    },
                )
    bind.execute(sa.text("UPDATE users SET preferences='{}'::jsonb"))


def reconcile_legacy(bind: sa.Connection) -> None:
    for user in bind.execute(sa.text("SELECT id,preferences,preference_deleted FROM users")):
        if user.preference_deleted:
            bind.execute(
                sa.text(
                    "UPDATE user_memory_facts SET status='deleted',value=NULL,"
                    "evidence_quote='',invalidated_at=now() WHERE user_id=:user"
                ),
                {"user": user.id},
            )
            continue
        values = user.preferences or {}
        for field, key in (
            ("interests", "interest"),
            ("soft_constraints", "avoid"),
            ("transport", "transport"),
        ):
            parts = (
                ([values[field]] if values.get(field) else [])
                if field == "transport"
                else values.get(field, [])
            )
            current = list(
                bind.scalars(
                    sa.text(
                        "SELECT value FROM user_memory_facts WHERE user_id=:user AND key=:key "
                        "AND scope='long_term' AND status='active' ORDER BY ordinal,created_at,id"
                    ),
                    {"user": user.id, "key": key},
                )
            )
            if parts == current:
                continue
            bind.execute(
                sa.text(
                    "UPDATE user_memory_facts SET status='superseded',invalidated_at=now() "
                    "WHERE user_id=:user AND key=:key AND scope='long_term' AND status='active'"
                ),
                {"user": user.id, "key": key},
            )
            bind.execute(
                sa.text(
                    "UPDATE user_memory_facts SET status='deleted',value=NULL,evidence_quote='',"
                    "invalidated_at=now() WHERE user_id=:user AND key=:key AND status='proposed'"
                ),
                {"user": user.id, "key": key},
            )
            for ordinal, value in enumerate(parts):
                bind.execute(
                    sa.text(
                        "INSERT INTO user_memory_facts(id,user_id,key,value,scope,status,source,"
                        "evidence_quote,ordinal,valid_from,last_confirmed_at) "
                        "VALUES (:id,:user,:key,CAST(:value AS jsonb),'long_term','active',"
                        "'migrated','',:ordinal,now(),now())"
                    ),
                    {
                        "id": uuid4(),
                        "user": user.id,
                        "key": key,
                        "value": json.dumps(value, ensure_ascii=False),
                        "ordinal": ordinal,
                    },
                )


def downgrade() -> None:
    # 保留新表，旧代码只读取仍active的兼容字段；删除/被取代正文不能恢复。
    bind = op.get_bind()
    for user in bind.execute(sa.text("SELECT id FROM users")):
        interests: list[object] = []
        constraints: list[object] = []
        transport: object = None
        for row in bind.execute(
            sa.text(
                "SELECT key,value FROM user_memory_facts WHERE user_id=:user "
                "AND scope='long_term' AND status='active' ORDER BY ordinal,created_at,id"
            ),
            {"user": user.id},
        ):
            if row.key == "interest":
                interests.append(row.value)
            elif row.key == "avoid":
                constraints.append(row.value)
            elif row.key == "transport":
                transport = row.value
        bind.execute(
            sa.text("UPDATE users SET preferences=CAST(:value AS jsonb) WHERE id=:user"),
            {
                "value": json.dumps(
                    {
                        "interests": interests,
                        "soft_constraints": constraints,
                        "transport": transport,
                    },
                    ensure_ascii=False,
                ),
                "user": user.id,
            },
        )
