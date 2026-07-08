from __future__ import annotations

import logging

import anyio
import uvicorn

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
    client = RenegotiationServiceClient(
        base_url=settings.renegotiation_service_base_url,
        retry_attempts=settings.renegotiation_service_retry_attempts,
    )
    producer = build_producer(settings)
    mcp = create_mcp_server(settings, client, producer)
    rest_api = create_rest_api(settings, client, producer)
    return settings, mcp, rest_api


settings, mcp, rest_api = build_app()


async def run_all() -> None:
    rest_config = uvicorn.Config(
        rest_api, host=settings.mcp_host, port=settings.docs_port, log_level="info"
    )
    rest_server = uvicorn.Server(rest_config)

    async with anyio.create_task_group() as tg:
        tg.start_soon(mcp.run_streamable_http_async)
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
