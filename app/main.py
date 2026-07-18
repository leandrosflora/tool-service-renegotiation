from __future__ import annotations

import asyncio
import logging

import anyio
import httpx
import uvicorn
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.starlette import StarletteInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import get_settings
from app.events.publisher import build_producer
from app.logging_setup import configure_logging
from app.mcp_server import create_mcp_server
from app.platform import PlatformMiddleware, metrics_response
from app.renegotiation_client import RenegotiationServiceClient
from app.rest_api import create_rest_api

configure_logging()
logger = logging.getLogger(__name__)


def build_app():
    settings = get_settings()
    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.internal_auth_service_name})
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_otlp_endpoint))
    )
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()

    client = RenegotiationServiceClient(settings)
    producer = build_producer(settings)
    mcp = create_mcp_server(settings, client, producer)
    rest_api = create_rest_api(settings, client, producer)

    @rest_api.get("/health/live", include_in_schema=False)
    async def health_live() -> dict[str, str]:
        return {"status": "live"}

    @rest_api.get("/health/ready", include_in_schema=False)
    async def health_ready() -> JSONResponse:
        failures: list[str] = []
        if settings.internal_auth_enabled and not settings.internal_auth_signing_key:
            failures.append("internal_auth_signing_key_missing")
        try:
            await asyncio.to_thread(producer.list_topics, 1)
        except Exception:
            failures.append("kafka_unavailable")
        try:
            async with httpx.AsyncClient(
                base_url=settings.renegotiation_service_base_url,
                timeout=2.0,
            ) as downstream:
                response = await downstream.get("/health/ready")
                if response.status_code != 200:
                    failures.append("renegotiation_service_not_ready")
        except Exception:
            failures.append("renegotiation_service_unavailable")

        return JSONResponse(
            {"status": "not_ready" if failures else "ready", "failures": failures},
            status_code=503 if failures else 200,
        )

    @rest_api.get("/metrics", include_in_schema=False)
    async def metrics():
        return metrics_response()

    rest_api.add_middleware(
        PlatformMiddleware,
        settings=settings,
        public_paths=("/health/live", "/health/ready", "/metrics", "/docs", "/openapi.json", "/redoc"),
        tenant_required_paths=("/clients", "/contracts", "/simulations", "/agreements"),
    )
    FastAPIInstrumentor.instrument_app(rest_api)

    mcp_asgi_app = mcp.streamable_http_app()
    mcp_asgi_app.add_middleware(
        PlatformMiddleware,
        settings=settings,
        public_paths=(),
        tenant_required_paths=("/mcp",),
    )
    StarletteInstrumentor.instrument_app(mcp_asgi_app)
    return settings, producer, mcp_asgi_app, rest_api


settings, producer, mcp_asgi_app, rest_api = build_app()


async def run_all() -> None:
    mcp_config = uvicorn.Config(
        mcp_asgi_app, host=settings.mcp_host, port=settings.mcp_port, log_level="info"
    )
    rest_config = uvicorn.Config(
        rest_api, host=settings.mcp_host, port=settings.docs_port, log_level="info"
    )
    mcp_server = uvicorn.Server(mcp_config)
    rest_server = uvicorn.Server(rest_config)

    async with anyio.create_task_group() as tg:
        tg.start_soon(mcp_server.serve)
        tg.start_soon(rest_server.serve)


if __name__ == "__main__":
    logger.info(
        "Starting tool-service-renegotiation MCP server on %s:%s and REST server on %s:%s",
        settings.mcp_host,
        settings.mcp_port,
        settings.mcp_host,
        settings.docs_port,
    )
    anyio.run(run_all)
