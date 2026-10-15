"""评分推送只含有界数值；失败不抹掉业务，幂等ID不含正文。"""

import json
from uuid import uuid4

import httpx
import pytest

from backend.adapters.tracing import push_scores

ENV = {
    "LANGFUSE_BASE_URL": "https://langfuse.example.test",
    "LANGFUSE_PUBLIC_KEY": "synthetic-public",
    "LANGFUSE_SECRET_KEY": "synthetic-secret",
}


def test_score_payload_is_numeric_and_replay_uses_same_id() -> None:
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/public/scores"
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": requests[-1]["id"]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        anchor = uuid4().hex
        assert push_scores(anchor, {"task_success": 1.0}, environment=ENV, http=http)
        assert push_scores(anchor, {"task_success": 1.0}, environment=ENV, http=http)
    assert requests[0] == requests[1]
    assert requests[0]["traceId"] == anchor and requests[0]["value"] == 1.0
    assert requests[0]["dataType"] == "NUMERIC" and "comment" not in requests[0]


@pytest.mark.parametrize("failure", [401, 503, "network"])
def test_score_failure_is_nonfatal(failure: int | str) -> None:
    def respond(_: httpx.Request) -> httpx.Response:
        if failure == "network":
            raise httpx.ConnectError("synthetic-private-server-body")
        assert isinstance(failure, int)
        return httpx.Response(failure, text="synthetic-private-server-body")

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        assert not push_scores(uuid4().hex, {"task_success": 0.0}, environment=ENV, http=http)


def test_invalid_or_unknown_score_never_makes_a_request() -> None:
    def never(_: httpx.Request) -> httpx.Response:
        pytest.fail("无效评分不能发送")

    with httpx.Client(transport=httpx.MockTransport(never)) as http:
        assert not push_scores(
            uuid4().hex, {"synthetic private quote": 1.0}, environment=ENV, http=http
        )
        assert not push_scores(
            uuid4().hex, {"task_success": float("nan")}, environment=ENV, http=http
        )
        assert not push_scores("not-trace", {"task_success": 1.0}, environment=ENV, http=http)


@pytest.mark.parametrize("partial", (False, True))
def test_explicit_batch_scores_use_one_ingestion_request_and_require_every_ack(
    partial: bool,
) -> None:
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/public/ingestion"
        payload = json.loads(request.content)
        requests.append(payload)
        batch = payload["batch"]
        assert len(batch) == 2
        assert all(e["type"] == "score-create" and "comment" not in e["body"] for e in batch)
        assert all(e["body"]["traceId"] == anchor for e in batch)
        return httpx.Response(
            207,
            json={
                "successes": [
                    {"id": e["id"], "status": 201} for e in (batch[:1] if partial else batch)
                ],
                "errors": [{"id": batch[-1]["id"], "status": 400}] if partial else [],
            },
        )

    anchor = uuid4().hex
    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        assert (
            push_scores(anchor, {"one": 1, "two": 2}, environment=ENV, http=http, batch=True)
            is not partial
        )
    assert len(requests) == 1


@pytest.mark.parametrize("receipt", [[], {}, {"errors": [], "successes": [{"id": {}}]}])
def test_malformed_batch_acknowledgement_is_nonfatal(receipt: object) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(207, json=receipt))
    ) as http:
        assert not push_scores(uuid4().hex, {"one": 1}, environment=ENV, http=http, batch=True)


@pytest.mark.parametrize("status", [None, 400, "201"])
def test_batch_matching_event_id_requires_success_status(status: object) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        event = json.loads(request.content)["batch"][0]
        return httpx.Response(
            207, json={"errors": [], "successes": [{"id": event["id"], "status": status}]}
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        assert not push_scores(uuid4().hex, {"one": 1}, environment=ENV, http=http, batch=True)
