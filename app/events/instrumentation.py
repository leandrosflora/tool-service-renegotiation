from __future__ import annotations

import functools
import logging
import uuid
from typing import Any, Awaitable, Callable

from confluent_kafka import Producer

from app.config import Settings
from app.events.publisher import publish_tool_executed_event
from app.logging_setup import correlation_id_var

logger = logging.getLogger(__name__)


def with_tool_event(
    tool_name: str, producer: Producer, settings: Settings
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Wraps a tool function so every invocation gets a correlation ID and publishes
    a tool.executed event (success or error) regardless of outcome."""

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            token = correlation_id_var.set(uuid.uuid4().hex)
            outcome = "error"
            try:
                result = await fn(*args, **kwargs)
                outcome = "success"
                return result
            finally:
                publish_tool_executed_event(producer, settings, tool_name, outcome, correlation_id_var.get())
                logger.info("Tool %s completed with outcome=%s", tool_name, outcome)
                correlation_id_var.reset(token)

        return wrapper

    return decorator
