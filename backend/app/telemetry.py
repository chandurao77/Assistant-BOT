"""OpenTelemetry instrumentation for Assistant Bot.

Provides distributed tracing (OTLP export) and Prometheus /metrics endpoint.
Enable with OTEL_ENABLED=true.  Traces are exported to OTEL_EXPORTER_OTLP_ENDPOINT
(default: http://otel-collector:4317).
"""
from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from prometheus_client import (
    Counter,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    REGISTRY,
)
from starlette.responses import Response
from fastapi import Request


# ── Prometheus metrics ────────────────────────────────────────────────────────
REQUEST_COUNT = Counter(
    "assistant_bot_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "assistant_bot_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

LLM_LATENCY = Histogram(
    "assistant_bot_llm_duration_seconds",
    "LLM generation latency (time to first token for streaming)",
    ["provider"],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0),
)

INGEST_PAGES = Counter(
    "assistant_bot_ingest_pages_total",
    "Total pages ingested",
    ["source"],
)

CACHE_HITS = Counter(
    "assistant_bot_cache_hits_total",
    "Semantic cache hits",
)

CACHE_MISSES = Counter(
    "assistant_bot_cache_misses_total",
    "Semantic cache misses",
)


def setup_telemetry(app, settings=None) -> None:
    """Initialise OpenTelemetry tracing + Prometheus metrics on a FastAPI app."""
    if settings is None:
        from app.config import get_settings
        settings = get_settings()
    otel_enabled = settings.otel_enabled

    if otel_enabled:
        resource = Resource.create({
            "service.name": "assistant-bot-backend",
            "service.version": "1.0.0",
        })
        provider = TracerProvider(resource=resource)
        endpoint = settings.otel_exporter_otlp_endpoint
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # Auto-instrument FastAPI (creates spans for every request)
        FastAPIInstrumentor.instrument_app(app)
        # Auto-instrument outgoing httpx calls (Ollama, Azure, Confluence)
        HTTPXClientInstrumentor().instrument()

    # Prometheus /metrics endpoint — protected by API key in production
    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request):
        if settings.environment == "production" and settings.api_key:
            api_key = request.headers.get("X-API-Key", "")
            if api_key != settings.api_key:
                from starlette.responses import JSONResponse
                return JSONResponse(status_code=403, content={"detail": "Forbidden"})
        return Response(
            content=generate_latest(REGISTRY),
            media_type=CONTENT_TYPE_LATEST,
        )
