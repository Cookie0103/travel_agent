"""真实API进程故障实验；只运行本地离线runtime，私有DSN从stdin读取。"""

import asyncio
import json
import socket
import sys

import uvicorn
from sqlalchemy import make_url

from backend.agent.runtime import EventSink
from backend.api.app import create_app
from backend.domain.execution import RunContext, RuntimeOutcome
from backend.domain.travel_request import RequestPatch
from backend.services.runs import RunService
from backend.services.sessions import SessionService
from backend.services.travel import TravelService
from tests.fakes import FakeRuntime


class InterruptedRuntime(FakeRuntime):
    def __init__(self, travel: TravelService) -> None:
        super().__init__(RuntimeOutcome(sdk_session_id="unused"))
        self.travel = travel

    async def execute(
        self,
        context: RunContext,
        prompt: str,
        sdk_session_id: str | None,
        emit: EventSink,
        cancelled: asyncio.Event,
    ) -> RuntimeOutcome:
        await self.travel.patch_request(
            context, RequestPatch.model_validate({"expected_revision": 1, "set": {"rooms": 2}})
        )
        print("business_committed", flush=True)
        await asyncio.Event().wait()
        return self.outcome


async def run(payload: dict[str, object]) -> None:
    sessions = SessionService(make_url(str(payload["dsn"])), demo_enabled=True)
    runs = None
    if payload.get("interrupt"):
        runtime = InterruptedRuntime(TravelService(sessions.database))
        runs = RunService(sessions.database, runtime_factory=lambda executor: runtime)
    app = create_app(sessions, runs_service=runs)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        while not server.started:
            if task.done():
                await task
                raise RuntimeError("API未启动")
            await asyncio.sleep(0.01)
        print(f"http://127.0.0.1:{port}", flush=True)
        await task


if __name__ == "__main__":
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(run(json.loads(sys.stdin.readline())))
