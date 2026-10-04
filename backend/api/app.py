"""FastAPI 薄入口；只调用服务用例，不直接查库或连接模型。"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Path, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from backend.api.events import stream_events
from backend.services.bookings import Booking, BookingService, HoldHotelInput
from backend.services.catalog import Article, CatalogService
from backend.services.common import ServiceError
from backend.services.models import ModelOption, model_options
from backend.services.plans import LockInput, PlanService, SavedPlan
from backend.services.preferences import (
    PreferencePatch,
    Preferences,
    PreferenceService,
    PreferenceVersion,
)
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
from backend.services.views import PlanView


def create_app(
    service: SessionService | None = None,
    *,
    runs_service: RunService | None = None,
    live_enabled: bool = False,
    trace_cloud: bool = False,
    booking_service: BookingService | None = None,
) -> FastAPI:
    sessions = service or SessionService.from_environment()
    runs = runs_service or RunService(
        sessions.database, live_enabled=live_enabled, trace_cloud=trace_cloud
    )
    travel = TravelService.from_environment(sessions.database, runs.live_enabled)
    plans = PlanService(travel)
    bookings = booking_service or BookingService(travel)
    preferences = PreferenceService(sessions.database)
    catalog = CatalogService(travel)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await runs.initialize()
            yield
        finally:
            await runs.close()
            await travel.close_data()
            await sessions.close()

    app = FastAPI(title="Travel Agent", lifespan=lifespan)

    @app.get("/models")
    async def models() -> list[ModelOption]:
        return model_options(os.environ, runs.live_enabled)

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, error: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status, content={"code": error.code, "message": str(error)}
        )

    async def identity(authorization: Annotated[str | None, Header()] = None) -> UUID:
        return await sessions.authenticate(authorization)

    @app.get("/preferences")
    async def get_preferences(user_id: Annotated[UUID, Depends(identity)]) -> Preferences:
        return await preferences.get(user_id)

    @app.patch("/preferences")
    async def patch_preferences(
        body: PreferencePatch, user_id: Annotated[UUID, Depends(identity)]
    ) -> Preferences:
        return await preferences.change(user_id, body)

    @app.delete("/preferences")
    async def delete_preferences(
        body: PreferenceVersion, user_id: Annotated[UUID, Depends(identity)]
    ) -> Preferences:
        return await preferences.change(user_id, body)

    @app.get("/health")
    async def health() -> dict[str, str]:
        await sessions.health()
        return {"status": "ok"}

    @app.get("/articles")
    async def articles() -> tuple[Article, ...]:
        return await catalog.articles()

    @app.get("/articles/{article_id}")
    async def article(article_id: Annotated[str, Path(min_length=1, max_length=100)]) -> Article:
        return await catalog.article(article_id)

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
    async def get_plan(plan_id: UUID, user_id: Annotated[UUID, Depends(identity)]) -> PlanView:
        return PlanView.model_validate(await plans.get(user_id, plan_id))

    @app.get("/plans/{plan_id}/calendar.ics")
    async def get_calendar(plan_id: UUID, user_id: Annotated[UUID, Depends(identity)]) -> Response:
        content, version = await plans.calendar(user_id, plan_id)
        return Response(
            content,
            media_type="text/calendar; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="trip-v{version}.ics"',
                "Cache-Control": "no-store",
            },
        )

    @app.post("/sessions/{session_id}/hotel-holds")
    async def hold_hotel(
        session_id: UUID, body: HoldHotelInput, user_id: Annotated[UUID, Depends(identity)]
    ) -> Booking:
        return await bookings.hold(RunContext(user_id, session_id), body)

    @app.get("/sessions/{session_id}/bookings")
    async def session_bookings(
        session_id: UUID, user_id: Annotated[UUID, Depends(identity)]
    ) -> tuple[Booking, ...]:
        return await bookings.list(RunContext(user_id, session_id))

    @app.get("/bookings/{booking_id}")
    async def get_booking(booking_id: UUID, user_id: Annotated[UUID, Depends(identity)]) -> Booking:
        return await bookings.get(user_id, booking_id)

    @app.post("/bookings/{booking_id}/confirm")
    async def confirm_booking(
        booking_id: UUID, user_id: Annotated[UUID, Depends(identity)]
    ) -> Booking:
        return await bookings.confirm(user_id, booking_id)

    @app.post("/bookings/{booking_id}/reconcile")
    async def reconcile_booking(
        booking_id: UUID, user_id: Annotated[UUID, Depends(identity)]
    ) -> Booking:
        return await bookings.reconcile(user_id, booking_id)

    @app.get("/plan-drafts/{draft_id}")
    async def get_draft(draft_id: UUID, user_id: Annotated[UUID, Depends(identity)]) -> PlanView:
        return PlanView.model_validate(await plans.get_draft(user_id, draft_id))

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
