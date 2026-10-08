"""真实杀进程实验的私有子进程；连接串只读stdin，不输出业务原文。"""

import asyncio
import json
import sys
from uuid import UUID

from sqlalchemy import make_url

from backend.domain.booking import OrderInput, SupplierOrder
from backend.domain.execution import RunContext
from backend.domain.plans import StageInput
from backend.domain.travel_request import RequestPatch
from backend.persistence.database import Database
from backend.services.bookings import BookingService
from backend.services.plans import PlanService
from backend.services.travel import TravelService
from mock_supplier.service import SupplierService


async def execute(payload: dict[str, object]) -> None:
    database = Database(make_url(str(payload["dsn"])))
    context = RunContext(UUID(str(payload["user_id"])), UUID(str(payload["session_id"])))
    service = TravelService(database)
    if payload["mode"] == "patch":
        await service.patch_request(context, RequestPatch.model_validate(payload["arguments"]))
    elif payload["mode"] == "stage":
        await PlanService(service).stage(context, StageInput.model_validate(payload["arguments"]))
    elif payload["mode"] in {"confirm_before_order", "confirm_after_order"}:

        class PausedSupplier(SupplierService):
            async def order(self, body: OrderInput) -> SupplierOrder:
                if payload["mode"] == "confirm_after_order":
                    await super().order(body)
                print("committed", flush=True)
                await asyncio.Event().wait()
                raise RuntimeError("unreachable")

        arguments = payload["arguments"]
        assert isinstance(arguments, dict)
        await BookingService(service, PausedSupplier(database)).confirm(
            context.user_id, UUID(str(arguments["booking_id"]))
        )
    else:
        raise ValueError("unsupported experiment")
    print("committed", flush=True)
    # 父进程在业务提交后、SDK尚未收到工具结果的窗口强制结束该自有子进程。
    await asyncio.Event().wait()


if __name__ == "__main__":
    payload = json.loads(sys.stdin.readline())
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(execute(payload))
