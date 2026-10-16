"""
Tool dependencies that read the caller from HTTP headers.

The agent sets ``X-User-Id`` and ``X-Conversation-Id`` on every tool call (a
LangGraph-context interceptor), so neither is a tool argument the model can fill.
"""
from uuid import UUID

from fastmcp.server.dependencies import get_http_headers

from src.core.identity.users import UserContext, parse_user_id


def get_user_context() -> UserContext:
    user_id = get_http_headers().get("x-user-id")
    if not user_id:
        raise ValueError("X-User-Id header is missing")
    return parse_user_id(user_id)


def get_conversation_id() -> UUID:
    conversation_id = get_http_headers().get("x-conversation-id")
    if not conversation_id:
        raise ValueError("X-Conversation-Id header is missing")
    return UUID(conversation_id)
