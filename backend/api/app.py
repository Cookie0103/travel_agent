"""FastAPI 薄入口；只调用服务用例，不直接查库或连接模型。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from backend.services.sessions import (
    DemoIdentity,
    DemoLogin,
    ServiceError,
    SessionService,
    SessionView,
)


def create_app(service: SessionService | None = None) -> FastAPI:
    sessions = service or SessionService.from_environment()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
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

    return app
