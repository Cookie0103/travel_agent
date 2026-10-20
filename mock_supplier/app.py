"""本地独立FastAPI供应商；四种故障只在显式测试/演示模式启用。"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.domain.booking import HoldInput, OrderInput, OrderLookup, SupplierHold, SupplierOrder
from backend.persistence.database import Database, configuration, database_url
from backend.services.common import ServiceError
from mock_supplier.service import SupplierService

Fault = Literal["delay", "rate_limit", "server_error", "lose_response"]


def create_app(database: Database | None = None, *, faults_enabled: bool = False) -> FastAPI:
    database = database or Database(database_url(configuration()))
    supplier = SupplierService(database)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await database.close()

    app = FastAPI(title="Travel simulated supplier", lifespan=lifespan)

    @app.exception_handler(ServiceError)
    async def error(request: Request, failure: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=failure.status,
            content={
                "code": failure.code,
                "message": str(failure),
            },
        )

    async def inject(fault: Fault | None, delay: float, *, orders: bool = False) -> None:
        if fault and not faults_enabled:
            raise HTTPException(403, "模拟故障未启用")
        if not 0 <= delay <= 5:
            raise HTTPException(422, "模拟延迟必须在0至5秒")
        if fault == "lose_response" and not orders:
            raise HTTPException(422, "丢响应故障仅用于下单")
        if fault == "delay":
            await asyncio.sleep(delay)
        if fault == "rate_limit":
            raise HTTPException(429, "模拟供应商限流", headers={"Retry-After": "1"})
        if fault == "server_error":
            raise HTTPException(500, "模拟供应商故障")

    @app.post("/holds", status_code=201)
    async def hold(
        body: HoldInput,
        x_mock_fault: Annotated[Fault | None, Header()] = None,
        x_mock_delay: Annotated[float, Header()] = 1,
    ) -> SupplierHold:
        await inject(x_mock_fault, x_mock_delay)
        return await supplier.hold(body)

    @app.post("/orders", response_model=SupplierOrder)
    async def order(
        body: OrderInput,
        x_mock_fault: Annotated[Fault | None, Header()] = None,
        x_mock_delay: Annotated[float, Header()] = 1,
    ) -> SupplierOrder | StreamingResponse:
        await inject(x_mock_fault, x_mock_delay, orders=True)
        result = await supplier.order(body)
        if x_mock_fault == "lose_response":

            async def lost_response() -> AsyncIterator[bytes]:
                yield b'{"order_id":'
                raise ConnectionError("模拟订单已创建而传输中断")

            return StreamingResponse(lost_response(), media_type="application/json")
        return result

    @app.get("/orders")
    async def lookup(
        client_ref: UUID,
        x_mock_fault: Annotated[Fault | None, Header()] = None,
        x_mock_delay: Annotated[float, Header()] = 1,
    ) -> OrderLookup:
        await inject(x_mock_fault, x_mock_delay)
        return await supplier.lookup(client_ref)

    return app
