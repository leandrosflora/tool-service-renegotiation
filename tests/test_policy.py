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


def test_consultar_contratos_is_allowed_in_same_turn_as_a_brand_new_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A brand new conversation's very first turn is signed with Started, not IdentificationPending
    # (conversation-orchestrator no longer transitions through IdentificationPending before
    # invoking the agent - that was JourneyTriggerClassifier's job, removed by
    # generalize-orchestrator-for-multi-agent). Without Started here, a customer's first message
    # could never chain "identify -> list contracts" in one turn.
    monkeypatch.setattr(
        policy,
        "current_execution_context",
        lambda: _context(stage="Started"),
    )

    decision = policy.authorize_tool("consultar_contratos", {"client_id": "client-1"})

    assert decision.context.journey_stage == "Started"


def test_consultar_contratos_is_denied_once_the_agreement_is_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        policy,
        "current_execution_context",
        lambda: _context(stage="AgreementConfirmed"),
    )

    with pytest.raises(policy.ToolPolicyDeniedError, match="not allowed"):
        policy.authorize_tool("consultar_contratos", {"client_id": "client-1"})


def test_consultar_cliente_and_contratos_allowed_from_handoff_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # conversation-orchestrator resets a conversation's State to a clean slate before calling the
    # agent whenever it was stuck in HandoffRequested (see IngestMessageUseCase.cs), rather than
    # signing the literal "HandoffRequested" journey_stage claim - but the turn that recovers a
    # conversation from an *older*, already-persisted HandoffRequested checkpoint can still be
    # signed with it (e.g. a retried/duplicate request racing the reset). consultar_cliente/
    # consultar_contratos must not be denied in that case or the agent could never look the
    # customer up again.
    monkeypatch.setattr(
        policy,
        "current_execution_context",
        lambda: _context(stage="HandoffRequested"),
    )

    client_decision = policy.authorize_tool("consultar_cliente", {"cpf": "11111111111"})
    contracts_decision = policy.authorize_tool("consultar_contratos", {"client_id": "client-1"})

    assert client_decision.context.journey_stage == "HandoffRequested"
    assert contracts_decision.context.journey_stage == "HandoffRequested"


def test_consultar_debitos_and_elegibilidade_allowed_in_same_turn_as_a_brand_new_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same reasoning as consultar_contratos above, one hop further: a single-contract customer's
    # very first message (signed with Started, not IdentificationPending - see above) should be
    # able to reach eligibility in the same turn as identification, not require a second customer
    # message just to answer a yes/no eligibility question - eligibility must be automatic and
    # transparent, never something the customer has to ask for.
    monkeypatch.setattr(
        policy,
        "current_execution_context",
        lambda: _context(stage="Started"),
    )

    debts_decision = policy.authorize_tool("consultar_debitos", {"contract_id": "contract-1"})
    eligibility_decision = policy.authorize_tool("validar_elegibilidade", {"contract_id": "contract-1"})

    assert debts_decision.context.journey_stage == "Started"
    assert eligibility_decision.context.journey_stage == "Started"


def test_consultar_debitos_and_elegibilidade_denied_once_the_agreement_is_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        policy,
        "current_execution_context",
        lambda: _context(stage="AgreementConfirmed"),
    )

    with pytest.raises(policy.ToolPolicyDeniedError, match="not allowed"):
        policy.authorize_tool("consultar_debitos", {"contract_id": "contract-1"})
    with pytest.raises(policy.ToolPolicyDeniedError, match="not allowed"):
        policy.authorize_tool("validar_elegibilidade", {"contract_id": "contract-1"})


def test_simular_proposta_allowed_in_same_turn_as_a_brand_new_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same reasoning as consultar_debitos/validar_elegibilidade above, one hop further: the agent
    # is now expected to proactively offer a simulation as soon as eligibility is confirmed
    # (see agent-runtime-renegotiation's prompts.py), so a single-contract customer's very first
    # message must be able to reach a simulation in the same turn too, not just eligibility.
    monkeypatch.setattr(
        policy,
        "current_execution_context",
        lambda: _context(stage="Started"),
    )
    arguments = {"contract_id": "contract-1", "installments": 12, "discount_percentage": 10.0}

    decision = policy.authorize_tool("simular_proposta", arguments)

    assert decision.context.journey_stage == "Started"


def test_simular_proposta_denied_once_the_agreement_is_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        policy,
        "current_execution_context",
        lambda: _context(stage="AgreementConfirmed"),
    )
    arguments = {"contract_id": "contract-1", "installments": 12, "discount_percentage": 10.0}

    with pytest.raises(policy.ToolPolicyDeniedError, match="not allowed"):
        policy.authorize_tool("simular_proposta", arguments)


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
