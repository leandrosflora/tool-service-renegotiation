from __future__ import annotations

import logging

import anyio
import uvicorn
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
from app.renegotiation_client import RenegotiationServiceClient
from app.rest_api import create_rest_api

configure_logging()
logger = logging.getLogger(__name__)


def build_app():
    settings = get_settings()

    # Exports to Jaeger via OTLP. HTTPXClientInstrumentor patches httpx globally, so it
    # also traces RenegotiationServiceClient's calls without touching that class directly.
    provider = TracerProvider(
        resource=Resource.create({"service.name": "tool-service-renegotiation"})
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_otlp_endpoint))
    )
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()

    client = RenegotiationServiceClient(
        base_url=settings.renegotiation_service_base_url,
        retry_attempts=settings.renegotiation_service_retry_attempts,
    )
    producer = build_producer(settings)
    mcp = create_mcp_server(settings, client, producer)
    rest_api = create_rest_api(settings, client, producer)
    FastAPIInstrumentor.instrument_app(rest_api)

    # FastMCP builds its own Starlette app for the streamable-HTTP MCP endpoint; instrument
    # that instance directly (mcp.run(...) would build and run it internally, leaving no
    # chance to instrument it first).
    mcp_asgi_app = mcp.streamable_http_app()
    StarletteInstrumentor.instrument_app(mcp_asgi_app)

    return settings, mcp_asgi_app, rest_api


settings, mcp_asgi_app, rest_api = build_app()


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
        "Starting tool-service-renegotiation MCP server on %s:%s and REST/Swagger docs on %s:%s",
        settings.mcp_host,
        settings.mcp_port,
        settings.mcp_host,
        settings.docs_port,
    )
    anyio.run(run_all)
