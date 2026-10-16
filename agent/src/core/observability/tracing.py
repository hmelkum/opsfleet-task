"""
OpenTelemetry tracing.

FastAPI's instrumentation opens a span for every request, and the code records its
events on the current span (see ``events``). Spans go to an OTLP/HTTP collector
(Jaeger in the prototype, Cloud Trace in production) when an endpoint is configured;
without one they are created but not exported.

Trace context crosses services in the W3C ``traceparent`` header, the one header
besides ``X-User-Id``. It is added explicitly on calls between our own services, so
third-party APIs never receive it.
"""
from fastapi import FastAPI
from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Probes are called every few seconds; tracing them would bury the real requests
_UNTRACED_PATHS = "livez,readyz,startupz,healthz"


def setup_tracing(service: str, otlp_endpoint: str | None) -> None:
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service}))
    if otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint.rstrip('/')}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def instrument_app(app: FastAPI) -> None:
    FastAPIInstrumentor.instrument_app(app, excluded_urls=_UNTRACED_PATHS)


def trace_headers() -> dict[str, str]:
    """The current trace context as headers for an outgoing call to one of our services."""
    headers: dict[str, str] = {}
    propagate.inject(headers)
    return headers
