from __future__ import annotations

import functools
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from confluent_kafka import Producer
from prometheus_client import Counter, Histogram

from app.config import Settings
from app.events.publisher import publish_tool_executed_event
from app.logging_setup import correlation_id_var

logger = logging.getLogger(__name__)

TOOL_EXECUTIONS = Counter(
    "tool_service_executions_total",
    "Governed tool executions.",
    ["tool", "outcome"],
)
TOOL_DURATION = Histogram(
    "tool_service_execution_duration_seconds",
    "Governed tool execution duration.",
    ["tool"],
)


def with_tool_event(
    tool_name: str, producer: Producer, settings: Settings
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            token = correlation_id_var.set(uuid.uuid4().hex)
            outcome = "error"
            started = time.perf_counter()
            try:
                result = await fn(*args, **kwargs)
                outcome = "success"
                return result
            finally:
                TOOL_EXECUTIONS.labels(tool_name, outcome).inc()
                TOOL_DURATION.labels(tool_name).observe(time.perf_counter() - started)
                publish_tool_executed_event(
                    producer,
                    settings,
                    tool_name,
                    outcome,
                    correlation_id_var.get(),
                )
                logger.info("Tool %s completed with outcome=%s", tool_name, outcome)
                correlation_id_var.reset(token)

        return wrapper

    return decorator
