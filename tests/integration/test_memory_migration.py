"""新事实迁移保留原顺序，回退只投影active；再升级保留旧代码的显式修改。"""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, create_engine, text

from backend.persistence.database import ROOT
from backend.persistence.temporary import temporary_database

pytestmark = pytest.mark.integration


def test_migration_and_rollback_never_restore_deleted_content(postgres_url: URL) -> None:
    with temporary_database(postgres_url, "test") as target:
        engine = create_engine(target, hide_parameters=True)
        try:
            with engine.begin() as db:
                config = Config(str(ROOT / "backend/persistence/alembic.ini"))
                config.attributes["connection"] = db
                # 该随机库没有事实；构造真实0017旧JSON状态，不触碰开发库。
                db.execute(text("DROP TABLE user_memory_facts"))
                db.execute(text("DROP TABLE user_profile_summaries"))
                db.execute(text("ALTER TABLE task_runs DROP COLUMN user_text"))
                db.execute(text("ALTER TABLE users DROP COLUMN memory_forgotten_at"))
                command.stamp(config, "0017")
                user_id = uuid4()
                db.execute(
                    text(
                        "INSERT INTO users(id,display_name,token_hash,token_expires_at,"
                        "preferences,preference_revision,preference_deleted) "
                        "VALUES(:id,'迁移合成用户',:token,:expires,CAST(:prefs AS jsonb),0,false)"
                    ),
                    {
                        "id": user_id,
                        "token": uuid4().hex,
                        "expires": datetime.now(UTC) + timedelta(days=1),
                        "prefs": json.dumps(
                            {"interests": ["庭园", "茶道"], "transport": None}, ensure_ascii=False
                        ),
                    },
                )
                command.upgrade(config, "head")
                facts = list(
                    db.execute(
                        text("SELECT key,value,source FROM user_memory_facts ORDER BY ordinal")
                    )
                )
                assert [(r.key, r.value, r.source) for r in facts] == [
                    ("interest", "庭园", "migrated"),
                    ("interest", "茶道", "migrated"),
                ]
                assert (
                    db.scalar(text("SELECT preferences FROM users WHERE id=:id"), {"id": user_id})
                    == {}
                )
                db.execute(
                    text(
                        "UPDATE user_memory_facts SET status='deleted',value=NULL,"
                        "evidence_quote='',invalidated_at=now() WHERE value='\"庭园\"'::jsonb"
                    )
                )
                command.downgrade(config, "0017")
                restored = db.scalar(
                    text("SELECT preferences FROM users WHERE id=:id"), {"id": user_id}
                )
                assert restored == {
                    "interests": ["茶道"],
                    "soft_constraints": [],
                    "transport": None,
                }
                # 旧代码显式编辑兼容列后再次升级，不能悄悄丢弃此编辑。
                db.execute(
                    text(
                        "UPDATE users SET preferences=CAST(:prefs AS jsonb),"
                        "preference_revision=1 WHERE id=:id"
                    ),
                    {
                        "id": user_id,
                        "prefs": json.dumps(
                            {"interests": ["美术"], "soft_constraints": [], "transport": "transit"},
                            ensure_ascii=False,
                        ),
                    },
                )
                command.upgrade(config, "head")
                active = list(
                    db.execute(
                        text(
                            "SELECT key,value FROM user_memory_facts WHERE status='active' "
                            "ORDER BY key,ordinal"
                        )
                    )
                )
                assert [(r.key, r.value) for r in active] == [
                    ("interest", "美术"),
                    ("transport", "transit"),
                ]
                assert (
                    db.scalar(
                        text("SELECT count(*) FROM user_memory_facts WHERE value='\"庭园\"'::jsonb")
                    )
                    == 0
                )
                command.downgrade(config, "0017")
                db.execute(text("UPDATE users SET preferences='{}'::jsonb,preference_deleted=true"))
                command.upgrade(config, "head")
                assert (
                    db.scalar(
                        text(
                            "SELECT count(*) FROM user_memory_facts WHERE status!='deleted' "
                            "OR value IS NOT NULL OR evidence_quote!=''"
                        )
                    )
                    == 0
                )
        finally:
            engine.dispose()
