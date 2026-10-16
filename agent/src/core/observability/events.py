"""
Observability events, recorded on the current OpenTelemetry span.

Each event is a span event with flat attributes: counts, tokens and timings, never
result rows or report bodies. The agent passes the turn's ids (conversation, turn,
user) explicitly, from the run's ``AgentContext``. They are also set on the span, so
a trace can be found by any of them.
"""
import json
from typing import Any

from opentelemetry import trace
from opentelemetry.util.types import AttributeValue

_TRACE_IDS = ("conversation_id", "turn_id", "user_id")


def emit(event: str, **fields: Any) -> None:
    span = trace.get_current_span()
    attributes = {key: _to_attribute(value) for key, value in fields.items() if value is not None}
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
