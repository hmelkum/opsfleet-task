"""Tracing events, trace propagation, the unhandled-error event and the health endpoints."""
import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace

from src.core.fastapi import health
from src.core.fastapi.errors import (
    UNHANDLED_ERROR_MESSAGE,
    register_unhandled_error_handler,
)
from src.core.fastapi.health import HealthChecks, create_health_router
from src.core.observability.events import emit, event_context
from src.core.observability.tracing import instrument_app, trace_headers


def test_events_land_on_the_current_span_with_the_turn_ids(spans):
    with trace.get_tracer("test").start_as_current_span("request"):
        with event_context(user_id="user_alice", turn_id="t1"):
            emit("sql_query", sql="SELECT 1", rows=1, empty=False, models=["a", "b"], pii_masked={"email": 1}, skipped=None)

    (span,) = spans.get_finished_spans()
    assert span.attributes["user_id"] == "user_alice" and span.attributes["turn_id"] == "t1"
    (event,) = span.events
    assert event.name == "sql_query"
    assert event.attributes["sql"] == "SELECT 1" and event.attributes["rows"] == 1 and event.attributes["empty"] is False
    assert tuple(event.attributes["models"]) == ("a", "b")
    assert event.attributes["pii_masked"] == '{"email": 1}'  # span attributes are flat
    assert "skipped" not in event.attributes


def test_trace_context_crosses_services_in_traceparent(spans):
    with trace.get_tracer("test").start_as_current_span("request") as span:
        headers = trace_headers()
    assert set(headers) == {"traceparent"}
    assert format(span.get_span_context().trace_id, "032x") in headers["traceparent"]


def test_unhandled_error_is_a_safe_500_and_an_event_on_the_request_span(spans):
    app = FastAPI()

    @app.get("/boom")
    async def boom():
        raise RuntimeError("connection string with secrets")

    register_unhandled_error_handler(app)
    instrument_app(app)

    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert response.status_code == 500 and response.json() == {"detail": UNHANDLED_ERROR_MESSAGE}
    assert "secrets" not in response.text
    events = [(e.name, dict(e.attributes)) for s in spans.get_finished_spans() for e in s.events]
    assert ("unhandled_error", {"method": "GET", "route": "/boom", "error": "RuntimeError"}) in events


def _client(checks: HealthChecks) -> TestClient:
    app = FastAPI()
    app.include_router(create_health_router(checks))
    return TestClient(app)


def test_liveness_never_depends_on_a_dependency():
    async def postgres_down():
        raise ConnectionError("db at 10.0.0.5 refused")

    checks = HealthChecks()
    checks.add("postgres", postgres_down)
    client = _client(checks)

    assert client.get("/livez").status_code == 200
    assert client.get("/readyz").status_code == 503
    assert client.get("/startupz").status_code == 503
    details = client.get("/healthz")
    assert details.status_code == 503
    assert details.json() == {"status": "unavailable", "checks": {"postgres": "failing: ConnectionError"}}
    assert "10.0.0.5" not in details.text


def test_startup_stays_passed_once_the_checks_have_passed():
    state = {"up": True}

    async def postgres():
        if not state["up"]:
            raise ConnectionError()

    checks = HealthChecks()
    checks.add("postgres", postgres)
    client = _client(checks)

    assert client.get("/startupz").status_code == 200
    state["up"] = False
    assert client.get("/startupz").status_code == 200  # startup is done; readiness takes over
    assert client.get("/readyz").status_code == 503


def test_a_hanging_check_fails_instead_of_blocking_the_probe(monkeypatch):
    monkeypatch.setattr(health, "CHECK_TIMEOUT_S", 0.05)

    async def hangs():
        await asyncio.sleep(5)

    checks = HealthChecks()
    checks.add("postgres", hangs)
    details = _client(checks).get("/healthz")
    assert details.status_code == 503 and details.json()["checks"] == {"postgres": "failing: TimeoutError"}
