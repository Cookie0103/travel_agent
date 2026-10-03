"""FastAPI 薄入口；只调用服务用例，不直接查库或连接模型。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.api.events import stream_events
from backend.services.common import ServiceError
from backend.services.plans import LockInput, PlanService, SavedPlan
from backend.services.runs import MessageInput, RunService, RunView
from backend.services.sessions import (
    DemoIdentity,
    DemoLogin,
    SessionService,
    SessionView,
)
from backend.services.travel import (
    RequestPatch,
    RequestUpdate,
    RunContext,
    TravelRequest,
    TravelService,
)


def create_app(
    service: SessionService | None = None,
    *,
    runs_service: RunService | None = None,
    live_enabled: bool = False,
) -> FastAPI:
    sessions = service or SessionService.from_environment()
    travel = TravelService(sessions.database)
    runs = runs_service or RunService(sessions.database, live_enabled=live_enabled)
    plans = PlanService(travel)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await runs.close()
            await sessions.close()

    app = FastAPI(title="Travel Agent", lifespan=lifespan)

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, error: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status, content={"code": error.code, "message": str(error)}
        )

    async def identity(authorization: Annotated[str | None, Header()] = None) -> UUID:
        return await sessions.authenticate(authorization)

    @app.get("/health")
    async def health() -> dict[str, str]:
        await sessions.health()
        return {"status": "ok"}

    @app.post("/demo/login", status_code=201)
    async def demo_login(body: DemoLogin) -> DemoIdentity:
        return await sessions.create_demo_user(body)

    @app.post("/sessions", status_code=201)
    async def new_session(user_id: Annotated[UUID, Depends(identity)]) -> SessionView:
        return await sessions.new_session(user_id)

    @app.get("/sessions/{session_id}")
    async def get_session(
        session_id: UUID, user_id: Annotated[UUID, Depends(identity)]
    ) -> SessionView:
        return await sessions.get_session(user_id, session_id)

    @app.get("/sessions/{session_id}/request")
    async def get_travel_request(
        session_id: UUID, user_id: Annotated[UUID, Depends(identity)]
    ) -> TravelRequest:
        return await travel.get_request(RunContext(user_id, session_id))

    @app.patch("/sessions/{session_id}/request")
    async def patch_travel_request(
        session_id: UUID, body: RequestPatch, user_id: Annotated[UUID, Depends(identity)]
    ) -> RequestUpdate:
        return await travel.patch_request(RunContext(user_id, session_id), body)

    @app.post("/sessions/{session_id}/messages", status_code=202)
    async def message(
        session_id: UUID, body: MessageInput, user_id: Annotated[UUID, Depends(identity)]
    ) -> RunView:
        return await runs.submit(user_id, session_id, body)

    @app.get("/runs/{run_id}")
    async def get_run(run_id: UUID, user_id: Annotated[UUID, Depends(identity)]) -> RunView:
        return await runs.get(user_id, run_id)

    @app.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: UUID, user_id: Annotated[UUID, Depends(identity)]) -> RunView:
        return await runs.cancel(user_id, run_id)

    @app.get("/runs/{run_id}/events")
    async def events(
        request: Request,
        run_id: UUID,
        user_id: Annotated[UUID, Depends(identity)],
        after: Annotated[int, Query(ge=0)] = 0,
        last_event_id: Annotated[str | None, Header()] = None,
    ) -> StreamingResponse:
        current = await runs.get(user_id, run_id)
        try:
            cursor = int(last_event_id) if last_event_id is not None else after
        except ValueError:
            raise ServiceError(422, "validation", "事件游标必须是整数") from None
        if not 0 <= cursor <= current.last_sequence:
            raise ServiceError(422, "validation", "事件游标超出此执行的范围")
        return StreamingResponse(
            stream_events(request, runs, user_id, run_id, cursor),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/plans/{plan_id}")
    async def get_plan(
        plan_id: UUID, user_id: Annotated[UUID, Depends(identity)]
    ) -> dict[str, object]:
        return await plans.get(user_id, plan_id)

    @app.get("/plan-drafts/{draft_id}")
    async def get_draft(
        draft_id: UUID, user_id: Annotated[UUID, Depends(identity)]
    ) -> dict[str, object]:
        return await plans.get_draft(user_id, draft_id)

    @app.post("/plan-drafts/{draft_id}/confirm")
    async def confirm_plan(
        draft_id: UUID, user_id: Annotated[UUID, Depends(identity)]
    ) -> SavedPlan:
        return await plans.confirm(user_id, draft_id)

    @app.patch("/plans/{plan_id}/locks")
    async def lock_items(
        plan_id: UUID, body: LockInput, user_id: Annotated[UUID, Depends(identity)]
    ) -> SavedPlan:
        return await plans.locks(user_id, plan_id, body)

    return app
