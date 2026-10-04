"""对外只读Streamable HTTP：SDK处理协议，认证会话复用现有旅行查询。"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import uvicorn
from mcp import types
from mcp.server import Server, ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from backend.domain.execution import RunContext
from backend.services.common import ServiceError
from backend.services.sessions import SessionService
from backend.services.travel import TravelService
from backend.tools.contracts import ToolResult
from backend.tools.execution import execute_observed
from backend.tools.travel import DEFINITIONS, TravelToolExecutor

READ_ONLY = tuple(
    definition
    for definition in DEFINITIONS
    if definition.name in {"search_content", "get_article", "search_places", "get_place_facts"}
)


def loopback_origin(value: str) -> bool:
    """SDK的:*匹配只检查前缀；另外拒绝伪造端口、userinfo及非Origin URL。"""
    try:
        parsed = urlsplit(value)
        return (
            not any(char.isspace() for char in value)
            and parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            and parsed.port is not None
            and parsed.port > 0
            and parsed.username is None
            and parsed.password is None
            and not (parsed.path or parsed.query or parsed.fragment)
        )
    except ValueError:
        return False


class AuthenticatedEndpoint:
    """每个HTTP请求重新认证；无共享MCP会话身份，也不接收工具中的身份字段。"""

    def __init__(self, sessions: SessionService, manager: StreamableHTTPSessionManager) -> None:
        self.sessions, self.manager = sessions, manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        origin = request.headers.get("origin")
        host_valid = loopback_origin("http://" + request.headers.get("host", ""))
        if not host_valid or (origin is not None and not loopback_origin(origin)):
            await JSONResponse(
                {"code": "blocked", "message": "仅允许本机Host和Origin"},
                status_code=421 if not host_valid else 403,
            )(scope, receive, send)
            return
        try:
            user_id = await self.sessions.authenticate(request.headers.get("authorization"))
            session = await self.sessions.get_session(user_id, scope["path_params"]["session_id"])
        except ServiceError as error:
            response = JSONResponse(
                {"code": error.code, "message": str(error)}, status_code=error.status
            )
            await response(scope, receive, send)
            return
        scope.setdefault("state", {})["travel_context"] = RunContext(user_id, session.session_id)
        await self.manager.handle_request(scope, receive, send)


def create_app(sessions: SessionService | None = None) -> Starlette:
    sessions = sessions or SessionService.from_environment()
    travel = TravelService(sessions.database)

    async def list_tools(
        context: ServerRequestContext[None, object], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=d.name,
                    description=d.description,
                    input_schema=d.schema,
                    annotations=types.ToolAnnotations(read_only_hint=True, destructive_hint=False),
                )
                for d in READ_ONLY
            ]
        )

    async def call_tool(
        context: ServerRequestContext[None, object], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        request = context.request
        run = (
            request.scope.get("state", {}).get("travel_context")
            if isinstance(request, Request)
            else None
        )
        definition = next((d for d in READ_ONLY if d.name == params.name), None)
        if not isinstance(run, RunContext) or definition is None:
            result = ToolResult({}, code="blocked")
        else:
            result = await execute_observed(
                TravelToolExecutor(travel),
                run,
                definition.name,
                params.arguments or {},
                lambda event: None,
                definition=definition,
            )
        payload = result.payload()
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
            structured_content=payload,
            is_error=result.code is not None,
        )

    server: Server[None] = Server(
        "travel-readonly", on_list_tools=list_tools, on_call_tool=call_tool
    )
    manager = StreamableHTTPSessionManager(
        server,
        stateless=True,
        json_response=True,
        max_request_body_size=64 * 1024,
        security_settings=TransportSecuritySettings(
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
        ),
    )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        try:
            async with manager.run():
                yield
        finally:
            await sessions.close()

    return Starlette(
        routes=[Route("/mcp/{session_id:uuid}", AuthenticatedEndpoint(sessions, manager))],
        lifespan=lifespan,
    )


def loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()


if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=8002, loop="backend.mcp.server:loop_factory")
