import json
from unittest.mock import MagicMock

import pytest

from app import events
from app.config import Settings
from app.events.publisher import publish_tool_executed_event

TENANT_ID = "00000000-0000-0000-0000-000000000001"


def make_settings() -> Settings:
    return Settings(kafka_tool_events_topic="tool.executed")


@pytest.fixture(autouse=True)
def tenant_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events.publisher, "current_tenant_id", lambda: TENANT_ID)


def test_publish_success_produces_keyed_message():
    producer = MagicMock()

    publish_tool_executed_event(producer, make_settings(), "consultar_cliente", "success", "corr-1")

    producer.produce.assert_called_once()
    args, kwargs = producer.produce.call_args
    assert args[0] == "tool.executed"
    assert kwargs["key"] == b"consultar_cliente"
    payload = json.loads(kwargs["value"])
    assert payload["outcome"] == "success"
    assert payload["correlation_id"] == "corr-1"
    assert payload["tenant_id"] == TENANT_ID
    producer.poll.assert_called_once_with(0)


def test_publish_error_outcome():
    producer = MagicMock()

    publish_tool_executed_event(producer, make_settings(), "consultar_debitos", "error", "corr-2")

    _, kwargs = producer.produce.call_args
    payload = json.loads(kwargs["value"])
    assert payload["outcome"] == "error"


def test_publish_never_includes_raw_arguments():
    producer = MagicMock()

    publish_tool_executed_event(producer, make_settings(), "consultar_cliente", "success", "corr-3")

    _, kwargs = producer.produce.call_args
    payload = json.loads(kwargs["value"])
    assert set(payload.keys()) == {"tenant_id", "tool_name", "outcome", "correlation_id"}
    assert "12345678900" not in kwargs["value"].decode("utf-8")


def test_publish_broker_unavailable_does_not_raise():
    producer = MagicMock()
    producer.produce.side_effect = RuntimeError("broker unavailable")

    publish_tool_executed_event(producer, make_settings(), "consultar_cliente", "success", "corr-4")
