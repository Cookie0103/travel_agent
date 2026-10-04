"""R10/R11：供应商HTTP失败/损坏返回/关联错误与Retry-After边界，无外部网络。"""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from uuid import uuid4

import httpx
import pytest

from backend.adapters.supplier import SupplierClient, SupplierError, retry_after
from backend.domain.booking import OrderInput, SupplierOrder


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://example.com",
        "http://user:secret@localhost",
        "http://localhost/path",
        "http://localhost?next=evil",
        "http://localhost:broken",
        "http://localhost:65536",
    ],
)
def test_supplier_url_cannot_reach_unapproved_hosts(url: str) -> None:
    with pytest.raises(ValueError, match="本地模拟"):
        SupplierClient(url)


@pytest.mark.parametrize("value", ["nan", "-1", "0.1", "broken", "１"])
def test_invalid_retry_after_does_not_request_short_retry(value: str) -> None:
    assert retry_after(value) == float("inf")


def test_retry_after_accepts_integer_seconds_and_http_date() -> None:
    assert retry_after("120") == 120 and retry_after(None) == 1
    assert retry_after(format_datetime(datetime.now(UTC) - timedelta(minutes=1), usegmt=True)) == 0
    value = retry_after(format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True))
    assert 28 <= value <= 30
    assert retry_after("9" * 5000) == float("inf")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body,code,ambiguous",
    [
        (500, "error", "provider_error", True),
        (302, "", "provider_error", True),
        (409, "{}", "conflict", False),
        (404, "{}", "blocked", False),
        (200, "broken", "provider_error", True),
        (200, "{}", "provider_error", True),
        (429, "{}", "rate_limited", False),
    ],
)
async def test_supplier_write_failures_are_classified_without_retry(
    status: int,
    body: str,
    code: str,
    ambiguous: bool,
) -> None:
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(status, content=body, headers={"Retry-After": "3"})

    client = SupplierClient(transport=httpx.MockTransport(respond))
    with pytest.raises(SupplierError) as failure:
        await client.order(OrderInput(client_ref=uuid4(), hold_id=uuid4()))
    assert failure.value.code == code and failure.value.ambiguous == ambiguous
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_wrong_order_reference_is_unknown_and_read_error_is_not_final_absence() -> None:
    order = SupplierOrder(
        client_ref=uuid4(), hold_id=uuid4(), order_id=uuid4(), created_at=datetime.now(UTC)
    )

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=order.model_dump(mode="json") if request.method == "POST" else {"order": {}}
        )

    client = SupplierClient(transport=httpx.MockTransport(respond))
    with pytest.raises(SupplierError) as failure:
        await client.order(OrderInput(client_ref=uuid4(), hold_id=uuid4()))
    assert failure.value.ambiguous
    with pytest.raises(SupplierError) as failure:
        await client.lookup(uuid4())
    assert not failure.value.ambiguous
