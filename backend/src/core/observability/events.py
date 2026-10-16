"""
Observability events, recorded on the current OpenTelemetry span.

Each event is a span event with flat attributes: SQL, counts, bytes, tokens and
timings, never result rows or report bodies. The ids of the current turn
(conversation, turn, user) live in a context variable, set once where a request
enters the service, so any code below can ``emit`` without passing them around.
They are also set on the span, so a trace can be found by any of them.
"""
import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from opentelemetry import trace
from opentelemetry.util.types import AttributeValue

_TRACE_IDS = ("conversation_id", "turn_id", "user_id")

_context: ContextVar[dict[str, str]] = ContextVar("event_context", default={})


@contextmanager
def event_context(**ids: Any) -> Iterator[None]:
    """Adds ids (conversation_id, turn_id, user_id) to every event emitted inside the block."""
    token = _context.set({**_context.get(), **{k: str(v) for k, v in ids.items() if v is not None}})
    try:
        yield
    finally:
        _context.reset(token)


def emit(event: str, **fields: Any) -> None:
    span = trace.get_current_span()
    attributes = {
        key: _to_attribute(value)
        for key, value in {**_context.get(), **fields}.items()
        if value is not None
    }
    for key in _TRACE_IDS:
        if key in attributes:
            span.set_attribute(key, attributes[key])
    span.add_event(event, attributes)


def _to_attribute(value: Any) -> AttributeValue:
    """Span attributes are flat: scalars stay, lists become lists of strings, anything else JSON."""
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return json.dumps(value, default=str, ensure_ascii=False)
