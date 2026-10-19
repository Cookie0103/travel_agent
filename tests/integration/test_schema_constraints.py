"""枚举型列的数据库CHECK：取值集合与代码里的权威定义一致，且迁移对既有数据兼容。"""

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, get_args
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import URL, Connection, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from backend.domain.booking import BookingStatus
from backend.domain.choices import ChoiceKind
from backend.domain.evidence import EvidenceKind
from backend.domain.execution import EventKind
from backend.domain.memory import MemoryScope, MemorySource, MemoryStatus
from backend.persistence import runs
from backend.persistence.database import ROOT
from backend.persistence.models import ChoiceCardRow
from backend.persistence.temporary import isolated_url, temporary_database
from backend.services.choices import card_from_row
from backend.services.runs import MessageInput

pytestmark = pytest.mark.integration

# 非终态事件种类不是task_runs.status；其余EventKind是终态，新增终态必须同步迁移与此处。
NON_TERMINAL_EVENTS = {
    "started",
    "text",
    "tool_started",
    "tool_finished",
    "presentation",
    "context_compacted",
}


def values(alias: Any) -> set[str]:
    return set(get_args(getattr(alias, "__value__", alias)))


# (表, CHECK名) -> 代码里的权威取值
EXPECTED = {
    ("task_runs", "ck_task_runs_status"): set(runs.ACTIVE)
    | (values(EventKind) - NON_TERMINAL_EVENTS),
    # "live"：早期MessageInput.mode取值，旧库行仍在（git历史），故保留在允许集合。
    ("task_runs", "ck_task_runs_mode"): set(get_args(MessageInput.model_fields["mode"].annotation))
    | {"live"},
    ("choice_cards", "ck_choice_cards_kind"): values(ChoiceKind),
    ("evidence", "ck_evidence_kind"): values(EvidenceKind),
    ("user_memory_facts", "ck_user_memory_facts_scope"): values(MemoryScope),
    ("user_memory_facts", "ck_user_memory_facts_status"): values(MemoryStatus),
    ("user_memory_facts", "ck_user_memory_facts_source"): values(MemorySource),
    ("bookings", "ck_bookings_status"): values(BookingStatus),
    ("catalog_entries", "ck_catalog_entries_kind"): {"places", "articles"},
}


def allowed(connection: Connection, table: str, name: str) -> set[str] | None:
    for check in inspect(connection).get_check_constraints(table):
        if check["name"] == name:
            # PG把IN (...)规范化成= ANY (ARRAY[...])；只取数组内的取值，不含payload的键名。
            body = re.search(r"ARRAY\[(.*?)\]", check["sqltext"])
            assert body, check["sqltext"]
            return set(re.findall(r"'([^']*)'", body.group(1)))
    return None


@contextmanager
def database_at(postgres_url: URL, revision: str) -> Iterator[Connection]:
    """只迁移到指定旧版本的随机库；名称形态同temporary_database，结束时强制删除。"""
    name = "travel_agent_test_" + uuid4().hex
    target = isolated_url(postgres_url, name)
    with psycopg.connect(
        host=postgres_url.host,
        port=postgres_url.port,
        dbname="postgres",
        user=postgres_url.username,
        password=postgres_url.password,
        autocommit=True,
    ) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        engine = create_engine(target, hide_parameters=True)
        try:
            with engine.begin() as connection:
                upgrade(connection, revision)
                yield connection
        finally:
            engine.dispose()
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def upgrade(connection: Connection, revision: str = "head") -> None:
    config = Config(str(ROOT / "backend/persistence/alembic.ini"))
    config.attributes["connection"] = connection
    command.upgrade(config, revision)


def run_insert(db: Connection, user: Any, session: Any, status: str, mode: str) -> Any:
    run = uuid4()
    db.execute(
        text(
            "INSERT INTO task_runs(id,user_id,session_id,client_message_id,mode,status,prompt,"
            "answer,last_sequence) VALUES (:i,:u,:s,:m,:mode,:status,'p','',0)"
        ),
        {"i": run, "u": user, "s": session, "m": uuid4(), "mode": mode, "status": status},
    )
    return run


def evidence_insert(db: Connection, user: Any, session: Any, kind: str) -> Any:
    evidence = uuid4()
    db.execute(
        text(
            "INSERT INTO evidence(id,user_id,session_id,kind,invalidated,payload) "
            "VALUES (:i,:u,:s,:k,false,'{}')"
        ),
        {"i": evidence, "u": user, "s": session, "k": kind},
    )
    return evidence


def seed(db: Connection) -> None:
    """每个枚举值至少一行，只填NOT NULL且无默认的列；旧新版本都能执行。"""
    user, session = uuid4(), uuid4()
    db.execute(
        text(
            "INSERT INTO users(id,display_name,token_hash,token_expires_at,preferences,"
            "preference_revision,preference_deleted) VALUES (:u,'合成用户',:t,:e,'{}',0,false)"
        ),
        {"u": user, "t": uuid4().hex, "e": datetime.now(UTC) + timedelta(days=1)},
    )
    db.execute(text("INSERT INTO sessions(id,user_id) VALUES (:s,:u)"), {"s": session, "u": user})
    modes = sorted(EXPECTED[("task_runs", "ck_task_runs_mode")])
    run_ids = [
        run_insert(db, user, session, status, modes[index % len(modes)])
        for index, status in enumerate(sorted(EXPECTED[("task_runs", "ck_task_runs_status")]))
    ]
    for mode in modes:
        run_insert(db, user, session, "completed", mode)
    for kind in sorted(EXPECTED[("choice_cards", "ck_choice_cards_kind")]):
        db.execute(
            text(
                "INSERT INTO choice_cards(id,session_id,source_run_id,kind,expected_revision,"
                "content) VALUES (:i,:s,:r,:k,0,'{}')"
            ),
            {"i": uuid4(), "s": session, "r": run_ids[0], "k": kind},
        )
    for kind in sorted(EXPECTED[("evidence", "ck_evidence_kind")]):
        evidence_insert(db, user, session, kind)
    for scope in sorted(EXPECTED[("user_memory_facts", "ck_user_memory_facts_scope")]):
        for status in sorted(EXPECTED[("user_memory_facts", "ck_user_memory_facts_status")]):
            for source in sorted(EXPECTED[("user_memory_facts", "ck_user_memory_facts_source")]):
                db.execute(
                    text(
                        "INSERT INTO user_memory_facts(id,user_id,key,scope,status,source,"
                        "evidence_quote,ordinal) VALUES (:i,:u,'interest',:sc,:st,:so,'',0)"
                    ),
                    {"i": uuid4(), "u": user, "sc": scope, "st": status, "so": source},
                )
    for status in sorted(EXPECTED[("bookings", "ck_bookings_status")]):
        evidence = evidence_insert(db, user, session, "hotel_offer")
        db.execute(
            text(
                "INSERT INTO bookings(id,user_id,session_id,evidence_id,payload) "
                "VALUES (:i,:u,:s,:e,CAST(:p AS jsonb))"
            ),
            {
                "i": uuid4(),
                "u": user,
                "s": session,
                "e": evidence,
                "p": json.dumps({"status": status, "history": []}),
            },
        )
    for kind in sorted(EXPECTED[("catalog_entries", "ck_catalog_entries_kind")]):
        db.execute(
            text("INSERT INTO catalog_entries(id,kind,city,payload) VALUES (:i,:k,'京都','{}')"),
            {"i": f"{kind}-{uuid4().hex}", "k": kind},
        )


def test_check_values_equal_code_definitions(postgres_url: URL) -> None:
    with temporary_database(postgres_url, "test") as target:
        engine = create_engine(target)
        try:
            with engine.connect() as connection:
                for (table, name), expected in EXPECTED.items():
                    assert allowed(connection, table, name) == expected, (table, name)
        finally:
            engine.dispose()


@pytest.mark.parametrize(
    "table,column",
    [
        ("task_runs", "status"),
        ("task_runs", "mode"),
        ("choice_cards", "kind"),
        ("evidence", "kind"),
        ("catalog_entries", "kind"),
        ("user_memory_facts", "scope"),
        ("user_memory_facts", "status"),
        ("user_memory_facts", "source"),
    ],
)
def test_database_rejects_unknown_value(postgres_url: URL, table: str, column: str) -> None:
    """合法行在CHECK下依旧可插入（升级后的旧行即是），未知取值由数据库拒绝。"""
    with database_at(postgres_url, "head") as db:
        seed(db)
        sample = dict(db.execute(text(f"SELECT * FROM {table} LIMIT 1")).mappings().one())
        sample[column] = "bad"
        if table == "catalog_entries":
            sample["id"] = "dup-" + uuid4().hex
        else:
            sample["id"] = uuid4()
        if table == "task_runs":
            sample["client_message_id"] = uuid4()
        names = ",".join(sample)
        marks = ",".join(
            f"CAST(:{key} AS jsonb)" if isinstance(value, (dict, list)) else f":{key}"
            for key, value in sample.items()
        )
        params = {
            key: json.dumps(value) if isinstance(value, (dict, list)) else value
            for key, value in sample.items()
        }
        with pytest.raises(IntegrityError, match="ck_"):
            with db.begin_nested():
                db.execute(text(f"INSERT INTO {table}({names}) VALUES ({marks})"), params)


def test_booking_status_inside_payload_is_constrained(postgres_url: URL) -> None:
    with database_at(postgres_url, "head") as db:
        seed(db)
        row = db.execute(text("SELECT user_id,session_id FROM bookings LIMIT 1")).one()
        evidence = evidence_insert(db, row.user_id, row.session_id, "hotel_offer")
        with pytest.raises(IntegrityError, match="ck_bookings_status"):
            with db.begin_nested():
                db.execute(
                    text(
                        "INSERT INTO bookings(id,user_id,session_id,evidence_id,payload) "
                        'VALUES (:i,:u,:s,:e,\'{"status":"cancelled_by_magic"}\')'
                    ),
                    {"i": uuid4(), "u": row.user_id, "s": row.session_id, "e": evidence},
                )


def test_upgrade_keeps_existing_rows_of_every_state(postgres_url: URL) -> None:
    """旧head(0021)灌入各状态样例行再升级：行数不变，升级后所有CHECK均已校验生效。"""
    with database_at(postgres_url, "0021") as db:
        seed(db)
        tables = {table for table, _ in EXPECTED}
        before = {t: db.scalar(text(f"SELECT count(*) FROM {t}")) for t in tables}
        upgrade(db)
        assert {t: db.scalar(text(f"SELECT count(*) FROM {t}")) for t in tables} == before
        unvalidated = db.scalar(
            text("SELECT count(*) FROM pg_constraint WHERE contype='c' AND NOT convalidated")
        )
        assert unvalidated == 0
        assert allowed(db, "bookings", "ck_bookings_status") is not None


def test_upgrade_refuses_unknown_existing_value_without_changing_data(postgres_url: URL) -> None:
    """旧库里已有非法取值：迁移明确失败并指出表列，不静默改数据。"""
    with database_at(postgres_url, "0021") as db:
        seed(db)
        db.execute(
            text("UPDATE task_runs SET status='weird' WHERE id=(SELECT id FROM task_runs LIMIT 1)")
        )
        with pytest.raises(Exception, match=r"task_runs\.status"):
            with db.begin_nested():
                upgrade(db)
        assert db.scalar(text("SELECT count(*) FROM task_runs WHERE status='weird'")) == 1
        assert inspect(db).get_check_constraints("task_runs") == []


def test_task_runs_session_created_index_exists(postgres_url: URL) -> None:
    with temporary_database(postgres_url, "test") as target:
        engine = create_engine(target)
        try:
            indexes = {
                i["name"]: i["column_names"] for i in inspect(engine).get_indexes("task_runs")
            }
        finally:
            engine.dispose()
        assert indexes.get("ix_task_runs_session_id_created_at") == ["session_id", "created_at"]


LEGACY_CONFIRM = {"option_id": "confirm", "label": "确认并继续", "value": "确认"}


def test_0023_converts_legacy_travel_details_cards_to_form_cards(postgres_url: URL) -> None:
    """0022状态下的travel_details旧卡升级后是普通form卡，经当前代码读出预选与时间原文。"""
    legacy = {
        "question": "确认一下出行安排",
        "options": [LEGACY_CONFIRM],
        "details": {
            "transport_options": [],
            "pace_options": [],
            "transport": "taxi",
            "pace": "慢节奏",
            "time_constraints": ["11月10日10:00抵达"],
        },
    }
    with database_at(postgres_url, "0022") as db:
        seed(db)
        session, run = db.execute(text("SELECT session_id, id FROM task_runs LIMIT 1")).one()
        ids = {name: uuid4() for name in ("full", "empty", "answered")}
        for name, content, answered in (
            ("full", legacy, None),
            ("empty", {"question": "q", "options": [LEGACY_CONFIRM], "details": {}}, None),
            ("answered", legacy, "confirm"),
        ):
            db.execute(
                text(
                    "INSERT INTO choice_cards(id,session_id,source_run_id,kind,expected_revision,"
                    "content,answered_option_id) VALUES (:i,:s,:r,'travel_details',1,"
                    "CAST(:c AS jsonb),:a)"
                ),
                {
                    "i": ids[name],
                    "s": session,
                    "r": run,
                    "c": json.dumps(content, ensure_ascii=False),
                    "a": answered,
                },
            )
        upgrade(db)
        assert db.scalar(text("SELECT count(*) FROM choice_cards WHERE kind='travel_details'")) == 0
        assert allowed(db, "choice_cards", "ck_choice_cards_kind") == values(ChoiceKind)
        with pytest.raises(IntegrityError, match="ck_choice_cards_kind"):
            with db.begin_nested():
                db.execute(
                    text(
                        "INSERT INTO choice_cards(id,session_id,source_run_id,kind,"
                        "expected_revision,content) VALUES (:i,:s,:r,'travel_details',1,'{}')"
                    ),
                    {"i": uuid4(), "s": session, "r": run},
                )
        rows = {
            name: db.execute(
                text(
                    "SELECT id,session_id,source_run_id,kind,expected_revision,content,"
                    "answered_option_id,created_at FROM choice_cards WHERE id=:i"
                ),
                {"i": i},
            ).one()
            for name, i in ids.items()
        }
        for row in rows.values():
            assert row.kind == "form" and "details" not in row.content
        full = card_from_row(ChoiceCardRow(**rows["full"]._mapping), 1)
        assert full.kind == "form" and full.form is not None and not full.stale
        by_key = {group.key: group for group in full.form.groups}
        assert list(by_key) == ["transport", "pace", "times"]
        assert by_key["transport"].selected == ("taxi",) and by_key["pace"].selected == ("relaxed",)
        assert by_key["times"].shown == ("11月10日10:00抵达",)
        empty = card_from_row(ChoiceCardRow(**rows["empty"]._mapping), 1)
        assert empty.form is not None
        assert [g.key for g in empty.form.groups] == ["transport", "pace"]
        assert all(g.selected == () for g in empty.form.groups)
        assert card_from_row(ChoiceCardRow(**rows["answered"]._mapping), 1).answered_option_id == (
            "confirm"
        )


def test_0023_downgrade_reallows_travel_details_and_upgrades_again(postgres_url: URL) -> None:
    with database_at(postgres_url, "head") as db:
        config = Config(str(ROOT / "backend/persistence/alembic.ini"))
        config.attributes["connection"] = db
        command.downgrade(config, "0022")
        assert allowed(db, "choice_cards", "ck_choice_cards_kind") == values(ChoiceKind) | {
            "travel_details"
        }
        command.upgrade(config, "head")
        assert allowed(db, "choice_cards", "ck_choice_cards_kind") == values(ChoiceKind)
