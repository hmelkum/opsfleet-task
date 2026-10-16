"""Bind the caller's trace headers to the event context for every HTTP request and MCP tool call."""
from typing import Any

from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext
from starlette.types import ASGIApp, Receive, Scope, Send

from src.core.observability.events import event_context

TRACE_HEADERS = {
    "x-user-id": "user_id",
    "x-turn-id": "turn_id",
    "x-conversation-id": "conversation_id",
}


class TraceContextMiddleware:
    """Pure ASGI, so the context is visible to the endpoint and to any streamed response body.

    Only the user comes from a header. Conversation and turn ids travel in request bodies,
    so the endpoints that receive them bind them.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        with event_context(user_id=headers.get("x-user-id")):
            await self._app(scope, receive, send)


class MCPTraceContextMiddleware(Middleware):
    """The same for MCP tool calls, whose headers are set by the agent's interceptor."""

    async def on_call_tool(self, context: MiddlewareContext, call_next) -> Any:
        headers = get_http_headers(include={"x-user-id"})
        with event_context(**{field: headers.get(header) for header, field in TRACE_HEADERS.items()}):
            return await call_next(context)
