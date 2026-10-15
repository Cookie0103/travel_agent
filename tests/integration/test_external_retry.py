"""真实计数事务与合成 HTTP；不联网、不更改正式配额。"""

import asyncio

import httpx
import pytest
from sqlalchemy import text

from backend.adapters.external_api import REQUEST_DEADLINE, ApiUsage, request_json
from backend.domain.execution import RunContext
from backend.domain.external_data import ExternalDataError
from backend.services.travel import TravelService
from tests.integration.test_travel import travel_setup as travel_setup

pytestmark = pytest.mark.integration


def test_mixed_failures_preserve_each_attempt_kind(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
) -> None:
    runner, travel, _ = travel_setup
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("private", request=request)
        return httpx.Response(503)

    async def exercise() -> None:
        usage = ApiUsage(travel.database, {}, run_limits=False)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            try:
                with pytest.raises(ExternalDataError) as failure:
                    await request_json(http, usage, "places", "GET", "https://test.invalid")
                assert failure.value.info.first_failure == "timeout"
                assert failure.value.info.kind == "upstream_5xx"
            finally:
                async with travel.database.sessions.begin() as db:
                    await db.execute(
                        text("UPDATE external_api_usage SET calls=calls-:n WHERE api='places'"),
                        {"n": usage.used.get("places", 0)},
                    )

    runner.run(exercise())


@pytest.mark.parametrize("blocked_by", ["quota", "deadline"])
def test_retry_skip_does_not_send_second_request(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], blocked_by: str
) -> None:
    runner, travel, _ = travel_setup

    async def exercise() -> None:
        usage = ApiUsage(travel.database, {})
        usage.run_caps["places"] = 1 if blocked_by == "quota" else 2
        token = REQUEST_DEADLINE.set(
            asyncio.get_running_loop().time() + 0.1 if blocked_by == "deadline" else None
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(503))
        ) as http:
            try:
                with pytest.raises(ExternalDataError) as failure:
                    await request_json(http, usage, "places", "GET", "https://test.invalid")
                assert failure.value.info.attempts == 1
                assert failure.value.info.retry_skipped == blocked_by
                assert failure.value.info.kind == (
                    "quota_exhausted" if blocked_by == "quota" else "upstream_5xx"
                )
                assert usage.used == {"places": 1}
            finally:
                REQUEST_DEADLINE.reset(token)
                async with travel.database.sessions.begin() as db:
                    await db.execute(
                        text("UPDATE external_api_usage SET calls=calls-1 WHERE api='places'")
                    )

    runner.run(exercise())


@pytest.mark.parametrize("failure", [429, 503, "timeout", "network", "json"])
def test_transient_retries_once_and_counts_both_requests(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], failure: int | str
) -> None:
    runner, travel, _ = travel_setup
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 2:
            return httpx.Response(200, json={"ok": True})
        if failure == "timeout":
            raise httpx.ReadTimeout("private upstream text", request=request)
        if failure == "network":
            raise httpx.ConnectError("private upstream text", request=request)
        if failure == "json":
            return httpx.Response(200, content="private malformed text")
        assert isinstance(failure, int)
        return httpx.Response(failure, headers={"Retry-After": "0"})

    async def exercise() -> None:
        usage = ApiUsage(travel.database, {}, run_limits=False)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            try:
                assert await request_json(http, usage, "places", "GET", "https://test.invalid") == {
                    "ok": True
                }
                assert calls == 2 and usage.used == {"places": 2}
                assert usage.observations[-1].attempts == 2
                assert usage.observations[-1].recovered_from is not None
            finally:
                async with travel.database.sessions.begin() as db:
                    await db.execute(
                        text("UPDATE external_api_usage SET calls=calls-:n WHERE api='places'"),
                        {"n": usage.used.get("places", 0)},
                    )

    runner.run(exercise())


@pytest.mark.parametrize(
    "status,kind,attempts",
    [(400, "bad_request", 1), (429, "rate_limited", 2), (503, "upstream_5xx", 2)],
)
def test_final_error_has_bounded_safe_metadata(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext],
    status: int,
    kind: str,
    attempts: int,
) -> None:
    runner, travel, _ = travel_setup

    async def exercise() -> None:
        usage = ApiUsage(travel.database, {}, run_limits=False)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    status, content="private raw body", headers={"Retry-After": "0"}
                )
            )
        ) as http:
            try:
                with pytest.raises(ExternalDataError) as failure:
                    await request_json(http, usage, "places", "GET", "https://test.invalid")
                assert failure.value.info.kind == kind
                assert failure.value.info.attempts == attempts
                assert "private" not in str(failure.value)
                assert usage.used == {"places": attempts}
            finally:
                async with travel.database.sessions.begin() as db:
                    await db.execute(
                        text("UPDATE external_api_usage SET calls=calls-:n WHERE api='places'"),
                        {"n": usage.used.get("places", 0)},
                    )

    runner.run(exercise())


@pytest.mark.parametrize("error,empty", [("not_found", True), ("wrong_path", False)])
def test_rakuten_404_only_not_found_is_empty(
    travel_setup: tuple[asyncio.Runner, TravelService, RunContext], error: str, empty: bool
) -> None:
    runner, travel, _ = travel_setup

    async def exercise() -> None:
        usage = ApiUsage(travel.database, {})
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(404, json={"error": error}))
        ) as http:
            if empty:
                assert await request_json(
                    http, usage, "rakuten", "GET", "https://test.invalid", empty_404=True
                ) == {"hotels": []}
            else:
                with pytest.raises(ExternalDataError) as failure:
                    await request_json(
                        http, usage, "rakuten", "GET", "https://test.invalid", empty_404=True
                    )
                assert failure.value.info.kind == "bad_request"

    runner.run(exercise())
