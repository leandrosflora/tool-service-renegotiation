from __future__ import annotations

import pytest

from app import policy
from app.platform import ToolExecutionContext


def _context(
    *,
    stage: str,
    message_id: str = "wamid-1",
    confirmation_message_id: str | None = None,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        tenant_id="00000000-0000-0000-0000-000000000001",
        caller_service="agent-runtime-renegotiation",
        conversation_id="conversation-1",
        message_id=message_id,
        journey_stage=stage,
        journey_version=7,
        confirmation_message_id=confirmation_message_id,
    )


def test_confirmation_requires_signed_current_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        policy,
        "current_execution_context",
        lambda: _context(stage="ConfirmationPending"),
    )

    with pytest.raises(policy.ToolPolicyDeniedError, match="confirmation evidence"):
        policy.authorize_tool("confirmar_acordo", {"simulation_id": "simulation-1"})


def test_confirmation_is_allowed_with_matching_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        policy,
        "current_execution_context",
        lambda: _context(
            stage="ConfirmationPending",
            message_id="wamid-confirm",
            confirmation_message_id="wamid-confirm",
        ),
    )

    decision = policy.authorize_tool(
        "confirmar_acordo",
        {"simulation_id": "simulation-1"},
    )

    assert decision.idempotency_key is not None
    assert "wamid-confirm" in decision.idempotency_key


def test_confirmation_is_denied_from_wrong_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        policy,
        "current_execution_context",
        lambda: _context(
            stage="EligibilityChecked",
            confirmation_message_id="wamid-1",
        ),
    )

    with pytest.raises(policy.ToolPolicyDeniedError, match="not allowed"):
        policy.authorize_tool("confirmar_acordo", {"simulation_id": "simulation-1"})


def test_consultar_contratos_is_allowed_in_same_turn_as_identification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # journey_stage is signed once at the start of the agent turn and never advances mid-turn,
    # so a turn that just identified the customer via consultar_cliente is still signed with
    # IdentificationPending when it immediately calls consultar_contratos next.
    monkeypatch.setattr(
        policy,
        "current_execution_context",
        lambda: _context(stage="IdentificationPending"),
    )

    decision = policy.authorize_tool("consultar_contratos", {"client_id": "client-1"})

    assert decision.context.journey_stage == "IdentificationPending"


def test_consultar_contratos_is_denied_before_identification_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        policy,
        "current_execution_context",
        lambda: _context(stage="Started"),
    )

    with pytest.raises(policy.ToolPolicyDeniedError, match="not allowed"):
        policy.authorize_tool("consultar_contratos", {"client_id": "client-1"})


def test_simulation_key_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        policy,
        "current_execution_context",
        lambda: _context(stage="EligibilityChecked"),
    )
    arguments = {
        "contract_id": "contract-1",
        "installments": 12,
        "discount_percentage": 10.0,
    }

    first = policy.authorize_tool("simular_proposta", arguments)
    second = policy.authorize_tool("simular_proposta", arguments)

    assert first.idempotency_key == second.idempotency_key
    assert first.idempotency_key is not None
    assert first.idempotency_key.startswith("simulate:")
