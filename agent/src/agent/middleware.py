import logging
import time
from collections.abc import Awaitable, Callable

import httpx
from google.genai import errors as genai_errors
from langchain.agents.middleware import (
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
    wrap_model_call,
    wrap_tool_call,
)
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.config import get_stream_writer
from langgraph.types import Command
from opentelemetry import trace

from src.agent.context import AgentContext
from src.chat.models import ChatChunkModel, ChatChunkType
from src.core.observability.events import emit

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

TOOL_UNAVAILABLE_MESSAGE = (
    "The tool is temporarily unavailable. Do not call it again in this turn; "
    "tell the user what you could not do and suggest trying again shortly."
)


def is_transient_model_error(exc: BaseException) -> bool:
    """Retry rate limits, server errors and network failures; never billing, auth or invalid requests."""
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, genai_errors.ServerError):
            return True
        if isinstance(current, genai_errors.ClientError):
            return current.code == 429
        if isinstance(current, (httpx.TimeoutException, httpx.TransportError)):
            return True
        current = current.__cause__
    return False


@wrap_tool_call
async def stream_tool_calls(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]
) -> ToolMessage | Command:
    """Emits every tool call as a ``tool_call`` chunk with its full arguments. Clients decide what to show."""
    get_stream_writer()(
        ChatChunkModel(
            type=ChatChunkType.TOOL_CALL,
            content={"name": request.tool_call["name"], "args": request.tool_call["args"]}
        ).model_dump()
    )
    return await handler(request)


def on_tool_error(exc: Exception, request: ToolCallRequest) -> str:
    """A tool call that raised (backend unreachable, transport error) becomes a message the model can act on."""
    logger.error("tool_failed tool=%s error=%r", request.tool_call["name"], exc)
    return TOOL_UNAVAILABLE_MESSAGE


@wrap_model_call
async def log_model_calls(
    request: ModelRequest,
    handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
) -> ModelResponse:
    """One ``llm_call`` span and event per model attempt (innermost, so retries and fallbacks are each counted)."""
    context: AgentContext = request.runtime.context  # type: ignore[union-attr]
    model = getattr(request.model, "model", type(request.model).__name__)
    with _tracer.start_as_current_span("llm_call", attributes={"model": model}):
        started = time.monotonic()
        try:
            response = await handler(request)
        except Exception as e:
            emit("llm_call", **context.event_ids(), model=model, outcome="error", error=describe_error(e), duration_ms=_ms(started))
            raise

        message = next((m for m in response.result if isinstance(m, AIMessage)), None)
        usage = (message.usage_metadata if message else None) or {}
        stats = context.stats
        stats.model_calls += 1
        stats.input_tokens += usage.get("input_tokens", 0)
        stats.output_tokens += usage.get("output_tokens", 0)
        if model not in stats.models:
            stats.models.append(model)
        emit(
            "llm_call",
            **context.event_ids(),
            model=model,
            outcome="ok",
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            tool_calls=len(message.tool_calls) if message else 0,
            duration_ms=_ms(started),
        )
        return response


@wrap_tool_call
async def log_tool_calls(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]
) -> ToolMessage | Command:
    """One ``tool`` span and ``tool_call`` event per tool call. ``rejected`` means the tool answered with an error result.

    The span is current while the tool runs, so an MCP call carries it to the backend as ``traceparent``.
    """
    context: AgentContext = request.runtime.context  # type: ignore[union-attr]
    name = request.tool_call["name"]
    context.stats.tool_calls += 1
    if name == "execute_sql_query":
        context.stats.sql_queries += 1

    with _tracer.start_as_current_span(f"tool {name}", attributes={"tool": name}):
        started = time.monotonic()
        result = await handler(request)

        outcome = "ok"
        if isinstance(result, ToolMessage):
            structured = ((result.artifact or {}).get("structured_content") or {}).get("result") or {}
            if result.status == "error":
                outcome = "error"
            elif structured.get("success") is False:
                outcome = "rejected"
        emit("tool_call", **context.event_ids(), tool=name, outcome=outcome, duration_ms=_ms(started))
        return result


def describe_error(exc: BaseException) -> str:
    """A short, log-safe description: the API status code if there is one, else the exception type."""
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, genai_errors.APIError):
            return f"{current.code} {current.status}"
        current = current.__cause__
    return type(exc).__name__


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
