"""U1首轮真实HTTP/离线工具/PG：不填表、已说事实保存、没说事实追问。"""

import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import URL

from backend.api.app import create_app
from backend.services.sessions import SessionService
from tests.integration.test_sessions import login

pytestmark = pytest.mark.integration


def test_first_offline_turn_extracts_only_spoken_facts_and_asks_for_missing(
    postgres_url: URL,
) -> None:
    with TestClient(
        create_app(SessionService(postgres_url, demo_enabled=True)),
        backend_options={"loop_factory": asyncio.SelectorEventLoop},
    ) as client:
        owner = login(client)
        sid = client.post("/sessions", headers=owner).json()["session_id"]
        base = f"/sessions/{sid}"
        sent = client.post(
            base + "/messages",
            headers=owner,
            json={
                "client_message_id": str(uuid4()),
                "text": "下周末两大人一小孩(5岁)去札幌，全程8万",
            },
        )
        assert sent.status_code == 202
        run_path = "/runs/" + sent.json()["run_id"]
        assert client.get(run_path + "/events", headers=owner).status_code == 200
        request = client.get(base + "/request", headers=owner).json()
        assert request["city"] == "札幌"
        assert request["adults"] == 2 and request["child_ages"] == [5]
        assert request["budget"] == "80000" and request["revision"] == 1
        assert request["start_date"] and request["end_date"]
        assert request["rooms"] is None and request["lodging_budget"] is None
        assert request["transport"] is None and request["departure_time"] is None
        assert request["field_sources"]["city"] == "conversation"
        assert request["field_sources"]["budget"] == "conversation"
        assert request["field_sources"]["rooms"] == "none"
        run = client.get(run_path, headers=owner).json()
        assert run["status"] == "completed"
        assert "房间" in run["answer"] and "右侧" not in run["answer"]
        assert not run["presentations"]


def test_empty_demo_asks_in_chat_instead_of_form_or_defaults(postgres_url: URL) -> None:
    with TestClient(
        create_app(SessionService(postgres_url, demo_enabled=True)),
        backend_options={"loop_factory": asyncio.SelectorEventLoop},
    ) as client:
        owner = login(client)
        sid = client.post("/sessions", headers=owner).json()["session_id"]
        base = f"/sessions/{sid}"
        sent = client.post(
            base + "/messages",
            headers=owner,
            json={"client_message_id": str(uuid4()), "text": "演示：比较酒店"},
        )
        run_path = "/runs/" + sent.json()["run_id"]
        client.get(run_path + "/events", headers=owner)
        run = client.get(run_path, headers=owner).json()
        assert run["status"] == "completed"
        assert "目的地" in run["answer"] and "右侧" not in run["answer"]
        request = client.get(base + "/request", headers=owner).json()
        assert request["revision"] == 0 and request["city"] is None and request["budget"] is None
        assert not run["presentations"]


@pytest.mark.parametrize("text", ["不要清空全程预算", "全程5万美元", "全程5万JPY，总预算8万美元"])
def test_unsupported_or_negative_fact_is_acknowledged_without_mutation_or_search(
    postgres_url: URL, text: str
) -> None:
    with TestClient(
        create_app(SessionService(postgres_url, demo_enabled=True)),
        backend_options={"loop_factory": asyncio.SelectorEventLoop},
    ) as client:
        owner = login(client)
        sid = client.post("/sessions", headers=owner).json()["session_id"]
        base = f"/sessions/{sid}"
        client.patch(
            base + "/request",
            headers=owner,
            json={"expected_revision": 0, "set": {"city": "札幌", "budget": "80000"}},
        )
        before = client.get(base + "/request", headers=owner).json()
        sent = client.post(
            base + "/messages",
            headers=owner,
            json={"client_message_id": str(uuid4()), "text": text},
        )
        run_path = "/runs/" + sent.json()["run_id"]
        events = client.get(run_path + "/events", headers=owner).text
        run = client.get(run_path, headers=owner).json()
        assert run["status"] == "completed" and "未更新" in run["answer"]
        assert '"kind":"tool_started"' not in events
        assert client.get(base + "/request", headers=owner).json() == before


def test_foreign_lodging_fact_is_saved_and_relation_stays_unknown(postgres_url: URL) -> None:
    with TestClient(
        create_app(SessionService(postgres_url, demo_enabled=True)),
        backend_options={"loop_factory": asyncio.SelectorEventLoop},
    ) as client:
        owner = login(client)
        sid = client.post("/sessions", headers=owner).json()["session_id"]
        base = f"/sessions/{sid}"
        client.patch(
            base + "/request",
            headers=owner,
            json={
                "expected_revision": 0,
                "set": {
                    "budget": "50000",
                    "rooms": 1,
                    "start_date": "2026-11-03",
                    "end_date": "2026-11-05",
                },
            },
        )
        sent = client.post(
            base + "/messages",
            headers=owner,
            json={"client_message_id": str(uuid4()), "text": "酒店每晚2万 EUR"},
        )
        run_path = "/runs/" + sent.json()["run_id"]
        client.get(run_path + "/events", headers=owner)
        request = client.get(base + "/request", headers=owner).json()
        assert request["revision"] == 2 and request["budget"] == "50000"
        assert request["lodging_budget"]["currency"] == "EUR"
        assert request["lodging_budget"]["amount"] == {"lower": "20000", "upper": "20000"}
        assert request["budget_relation"]["status"] == "unknown"
        assert request["budget_relation"]["total_lower"] == "40000"
        assert request["budget_relation"]["currency"] == "EUR"
        run = client.get(run_path, headers=owner).json()
        assert run["status"] == "completed" and "EUR" in run["answer"]
        assert not run["presentations"]
