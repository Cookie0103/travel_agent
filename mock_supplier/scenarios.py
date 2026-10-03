"""评测/演示的服务端故障场景；只在暂留接口触发，不让模型设置故障。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastapi import Request
from pydantic import ValidationError
from starlette.responses import Response

from backend.domain.booking import HoldInput
from backend.persistence.database import Database
from mock_supplier.app import create_app

type SupplierFault = Literal["supplier_500", "supplier_429", "supplier_timeout"]


@dataclass(frozen=True)
class HoldAttempt:
    client_ref: UUID
    fault: SupplierFault | None


class SupplierScenario:
    def __init__(self, database: Database) -> None:
        self.fault: SupplierFault | None = None
        self.attempts: list[HoldAttempt] = []
        self.app = create_app(database, faults_enabled=True)

        @self.app.middleware("http")
        async def inject(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            if request.url.path == "/holds" and request.method == "POST":
                try:
                    body = HoldInput.model_validate_json(await request.body())
                    self.attempts.append(HoldAttempt(body.client_ref, self.fault))
                except ValidationError:
                    pass  # 非法body仍由既有API返回422，不伪造供应商尝试。
            if self.fault and request.url.path == "/holds":
                fault = {
                    "supplier_500": "server_error",
                    "supplier_429": "rate_limit",
                    "supplier_timeout": "delay",
                }[self.fault]
                request.scope["headers"] = [
                    *request.scope["headers"],
                    (b"x-mock-fault", fault.encode()),
                    (b"x-mock-delay", b"3"),
                ]
            return await call_next(request)
