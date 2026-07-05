from __future__ import annotations

import logging

from app.config import get_settings
from app.events.publisher import build_producer
from app.logging_setup import configure_logging
from app.mcp_server import create_mcp_server
from app.renegotiation_client import RenegotiationServiceClient

configure_logging()
logger = logging.getLogger(__name__)


def build_app():
    settings = get_settings()
    client = RenegotiationServiceClient(
        base_url=settings.renegotiation_service_base_url,
        retry_attempts=settings.renegotiation_service_retry_attempts,
    )
    producer = build_producer(settings)
    return create_mcp_server(settings, client, producer)


mcp = build_app()


if __name__ == "__main__":
    logger.info(
        "Starting tool-service-renegotiation MCP server on %s:%s",
        get_settings().mcp_host,
        get_settings().mcp_port,
    )
    mcp.run(transport="streamable-http")
