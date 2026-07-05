from __future__ import annotations

import json
import logging

from confluent_kafka import Producer

from app.config import Settings

logger = logging.getLogger(__name__)


def build_producer(settings: Settings) -> Producer:
    return Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})


def publish_tool_executed_event(
    producer: Producer,
    settings: Settings,
    tool_name: str,
    outcome: str,
    correlation_id: str | None = None,
) -> None:
    """Publishes a tool.executed event keyed by tool name.

    The payload intentionally never includes tool arguments (CPF, contract IDs, etc.)
    so there is no raw sensitive identifier to leak into the audit trail.
    Never raises: any failure to enqueue or deliver is logged and swallowed.
    """
    topic = settings.kafka_tool_events_topic
    event = {
        "tool_name": tool_name,
        "outcome": outcome,
        "correlation_id": correlation_id,
    }

    try:
        producer.produce(
            topic,
            key=tool_name.encode("utf-8"),
            value=json.dumps(event).encode("utf-8"),
            on_delivery=_make_delivery_callback(tool_name, topic),
        )
        producer.poll(0)
    except Exception:
        logger.error("Failed to publish tool.executed event for tool %s", tool_name, exc_info=True)


def _make_delivery_callback(tool_name: str, topic: str):
    def _on_delivery(err, _msg) -> None:
        if err is not None:
            logger.error("Kafka delivery failed for tool %s on topic %s: %s", tool_name, topic, err)

    return _on_delivery
