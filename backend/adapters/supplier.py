"""模拟供应商HTTP边界；不自动重试，不把未知写响应当失败或成功。"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError

from backend.domain.booking import HoldInput, OrderInput, OrderLookup, SupplierHold, SupplierOrder
from backend.domain.execution import ErrorCode


@dataclass
class SupplierError(RuntimeError):
    code: ErrorCode
    ambiguous: bool = False
    retry_after: float | None = None


class SupplierGateway(Protocol):
    async def hold(self, body: HoldInput) -> SupplierHold: ...
    async def order(self, body: OrderInput) -> SupplierOrder: ...
    async def lookup(self, client_ref: UUID) -> OrderLookup: ...


class SupplierClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url or os.environ.get("MOCK_SUPPLIER_URL", "http://127.0.0.1:8001")
        parsed = urlsplit(self.base_url)
        try:
            _ = parsed.port
        except ValueError:
            raise ValueError("只允许有效的本地模拟供应商地址") from None
        if (
            parsed.scheme != "http"
            # 不变量：仅访问固定的模拟供应商；Railway 私网不开放任意服务名。
            or parsed.hostname
            not in {"127.0.0.1", "localhost", "mock_supplier", "supplier.railway.internal"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("只允许本地模拟供应商地址")
        self.headers = headers or {}
        self.transport = transport

    async def _request(
        self,
        method: str,
        path: str,
        body: BaseModel | None = None,
        *,
        client_ref: UUID | None = None,
    ) -> object:
        writing = method == "POST"
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=2,
                trust_env=False,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = await client.request(
                    method,
                    path,
                    json=body.model_dump(mode="json") if body else None,
                    params={"client_ref": str(client_ref)} if client_ref else None,
                    headers=self.headers,
                )
        except httpx.TimeoutException:
            raise SupplierError("timeout", ambiguous=writing) from None
        except httpx.HTTPError:
            raise SupplierError("unavailable", ambiguous=writing) from None
        if response.status_code == 429:
            raise SupplierError(
                "rate_limited", retry_after=retry_after(response.headers.get("Retry-After"))
            )
        if response.status_code >= 500 or 300 <= response.status_code < 400:
            raise SupplierError("provider_error", ambiguous=writing)
        if not response.is_success:
            raise SupplierError("conflict" if response.status_code == 409 else "blocked")
        try:
            return response.json()
        except ValueError:
            raise SupplierError("provider_error", ambiguous=writing) from None

    async def hold(self, body: HoldInput) -> SupplierHold:
        try:
            result = SupplierHold.model_validate(await self._request("POST", "/holds", body))
            if result.client_ref != body.client_ref or result.offer != body.offer:
                raise ValueError
            return result
        except (ValidationError, ValueError):
            raise SupplierError("provider_error", ambiguous=True) from None

    async def order(self, body: OrderInput) -> SupplierOrder:
        try:
            result = SupplierOrder.model_validate(await self._request("POST", "/orders", body))
            if (result.client_ref, result.hold_id) != (body.client_ref, body.hold_id):
                raise ValueError
            return result
        except (ValidationError, ValueError):
            raise SupplierError("provider_error", ambiguous=True) from None

    async def lookup(self, client_ref: UUID) -> OrderLookup:
        try:
            result = OrderLookup.model_validate(
                await self._request("GET", "/orders", client_ref=client_ref)
            )
            if result.order and (result.order.client_ref != client_ref or result.absence_final):
                raise ValueError
            return result
        except (ValidationError, ValueError):
            raise SupplierError("provider_error") from None


def retry_after(header: str | None) -> float:
    """RFC9110允许整数秒或HTTP-date；非法值不缩短真实退避。"""
    if header is None:
        return 1
    if header.isascii() and header.isdigit():
        return float(header)
    try:
        date = parsedate_to_datetime(header)
        if date.utcoffset() is None:
            return float("inf")
        return max(0, (date - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return float("inf")
