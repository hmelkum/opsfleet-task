from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from mcp.types import CallToolResult

from src.core.observability.tracing import trace_headers


@dataclass
class TurnStats:
    """Counters for one turn, updated by the observability middleware."""
    model_calls: int = 0
    tool_calls: int = 0
    sql_queries: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    models: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentContext:
    """Per-run context. Lives only in this run's LangGraph runtime, never in shared state."""
    user_id: str
    conversation_id: UUID
    turn_id: UUID | None = None
    stats: TurnStats = field(default_factory=TurnStats)

    def event_ids(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "conversation_id": str(self.conversation_id),
            "turn_id": str(self.turn_id) if self.turn_id else None,
        }


async def add_identity_headers(request: MCPToolCallRequest, handler) -> CallToolResult:
    """Sets the caller on every MCP tool call, so identity is never a tool argument the model fills.

    Stateless: reads the run's own context, which makes it safe under concurrent requests.
    """
    context: AgentContext = request.runtime.context  # type: ignore[union-attr]
    headers = {
        "X-User-Id": context.user_id,
        "X-Conversation-Id": str(context.conversation_id),
    }
    if context.turn_id:
        headers["X-Turn-Id"] = str(context.turn_id)
    headers.update(trace_headers())  # the current tool span continues on the backend
    return await handler(request.override(headers=headers))
