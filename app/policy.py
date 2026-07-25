from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.platform import ToolExecutionContext, current_execution_context


class ToolPolicyDeniedError(PermissionError):
    pass


READ_TOOL_STAGES: dict[str, set[str]] = {
    "consultar_cliente": {
        "Started",
        "IdentificationPending",
        "AuthenticationPending",
        "CustomerIdentified",
        "ContractSelectionPending",
        "ContractSelected",
        "EligibilityChecked",
        "SimulationParametersPending",
        "ProposalAvailable",
        "ProposalSelected",
        "ConfirmationPending",
        # conversation-orchestrator resets a stuck conversation's State to a clean slate before
        # calling the agent whenever it was persisted as HandoffRequested (see
        # IngestMessageUseCase.cs), so a customer whose conversation was previously handed off can
        # be picked back up by the bot if no human ever took over. An older, already-persisted
        # HandoffRequested checkpoint can still reach here in edge cases (e.g. a retried/duplicate
        # request racing the reset) - without this, consultar_cliente would be denied on that turn,
        # the agent would fail to look the customer up, and would likely recommend handoff again,
        # permanently re-locking the conversation.
        "HandoffRequested",
    },
    "consultar_contratos": {
        # Started is included alongside CustomerIdentified onward because the journey_stage claim
        # is signed once per agent turn (see agent-runtime-renegotiation's tool_service.py) and
        # never advances mid-turn - a brand new conversation's very first turn is signed with
        # Started (conversation-orchestrator no longer transitions Started -> IdentificationPending
        # before invoking the agent; that was JourneyTriggerClassifier's job, removed by
        # generalize-orchestrator-for-multi-agent), so without Started here the natural same-turn
        # chain "consultar_cliente identifies them -> consultar_contratos lists their contracts" is
        # always denied on a customer's very first message, forcing an unnecessary extra round
        # trip. consultar_contratos itself requires a client_id that can only come from a
        # consultar_cliente call already made from this stage, so this doesn't weaken the
        # identification requirement - it just lets both calls land in one turn.
        # IdentificationPending is kept for backward compatibility even though nothing produces it
        # as a milestone today - harmless to allow, costs nothing to leave in the set.
        "Started",
        "IdentificationPending",
        "CustomerIdentified",
        "ContractSelectionPending",
        "ContractSelected",
        "EligibilityChecked",
        "SimulationParametersPending",
        "ProposalAvailable",
        "ProposalSelected",
        "ConfirmationPending",
        # Same reasoning as consultar_cliente above: lets the same-turn identify+list-contracts
        # chain succeed on the turn that reopens a previously handed-off conversation.
        "HandoffRequested",
    },
    "consultar_debitos": {
        # Started/IdentificationPending/CustomerIdentified/ContractSelectionPending included for
        # the same reason as consultar_contratos above: the journey_stage claim is fixed at
        # turn-start, so without these a single-contract customer's very first message could never
        # reach debts/eligibility in the same turn as identification - eligibility must be an
        # automatic, transparent check, never something the customer has to explicitly ask for and
        # wait a whole extra turn on. consultar_debitos requires a contract_id that can only
        # legitimately come from a consultar_contratos call already made from this same stage, so
        # this doesn't weaken the requirement, it just lets the whole chain land in one turn.
        "Started",
        "IdentificationPending",
        "CustomerIdentified",
        "ContractSelectionPending",
        "ContractSelected",
        "EligibilityChecked",
        "SimulationParametersPending",
        "ProposalAvailable",
        "ProposalSelected",
        "ConfirmationPending",
        "HandoffRequested",
    },
    "validar_elegibilidade": {
        # Same reasoning as consultar_debitos above.
        "Started",
        "IdentificationPending",
        "CustomerIdentified",
        "ContractSelectionPending",
        "ContractSelected",
        "EligibilityChecked",
        "SimulationParametersPending",
        "HandoffRequested",
    },
    "gerar_documento": {
        "AgreementConfirmed",
        "DocumentAvailable",
        "Completed",
    },
}

SIMULATION_STAGES = {
    # Started/IdentificationPending/CustomerIdentified/ContractSelectionPending included for the
    # same reason as consultar_debitos/validar_elegibilidade above: the journey_stage claim is
    # fixed at turn-start, so without these a single-contract customer's very first message could
    # never reach a simulation in the same turn as identification+eligibility - the agent is now
    # expected to proactively offer a simulation as soon as eligibility is confirmed, not wait for
    # the customer to ask, so that whole chain has to be able to land in one turn.
    # simular_proposta requires a contract_id that can only legitimately come from a
    # consultar_contratos call already made from this same stage, so this doesn't weaken the
    # requirement, it just lets the chain land in one turn.
    "Started",
    "IdentificationPending",
    "CustomerIdentified",
    "ContractSelectionPending",
    "ContractSelected",
    "EligibilityChecked",
    "SimulationParametersPending",
}

CONFIRMATION_STAGES = {
    "ProposalSelected",
    "ConfirmationPending",
}


@dataclass(frozen=True)
class PolicyDecision:
    context: ToolExecutionContext
    idempotency_key: str | None = None


def authorize_tool(tool_name: str, arguments: dict[str, Any] | None = None) -> PolicyDecision:
    context = current_execution_context()
    arguments = arguments or {}

    if context.caller_service != "agent-runtime-renegotiation":
        raise ToolPolicyDeniedError("Only agent-runtime-renegotiation may execute governed tools.")

    if tool_name in READ_TOOL_STAGES:
        _require_stage(tool_name, context, READ_TOOL_STAGES[tool_name])
        return PolicyDecision(context)

    if tool_name == "simular_proposta":
        _require_stage(tool_name, context, SIMULATION_STAGES)
        required = ("contract_id", "installments", "discount_percentage")
        if any(name not in arguments for name in required):
            raise ToolPolicyDeniedError("Simulation arguments are incomplete.")
        return PolicyDecision(
            context,
            _simulation_idempotency_key(context, arguments),
        )

    if tool_name == "confirmar_acordo":
        _require_stage(tool_name, context, CONFIRMATION_STAGES)
        if not context.confirmation_message_id:
            raise ToolPolicyDeniedError("Explicit confirmation evidence is required.")
        if context.confirmation_message_id != context.message_id:
            raise ToolPolicyDeniedError("Confirmation evidence must belong to the current message.")
        simulation_id = arguments.get("simulation_id")
        if not isinstance(simulation_id, str) or not simulation_id:
            raise ToolPolicyDeniedError("simulation_id is required.")
        return PolicyDecision(
            context,
            f"confirm:{context.tenant_id}:{context.conversation_id}:"
            f"{context.confirmation_message_id}:{simulation_id}",
        )

    raise ToolPolicyDeniedError(f"Tool '{tool_name}' is not registered in the policy.")


def _require_stage(
    tool_name: str,
    context: ToolExecutionContext,
    allowed_stages: set[str],
) -> None:
    if context.journey_stage not in allowed_stages:
        raise ToolPolicyDeniedError(
            f"Tool '{tool_name}' is not allowed from journey stage '{context.journey_stage}'."
        )


def _simulation_idempotency_key(
    context: ToolExecutionContext,
    arguments: dict[str, Any],
) -> str:
    canonical = json.dumps(
        {
            "tenant_id": context.tenant_id,
            "conversation_id": context.conversation_id,
            "message_id": context.message_id,
            "journey_version": context.journey_version,
            "contract_id": arguments["contract_id"],
            "installments": int(arguments["installments"]),
            "discount_percentage": float(arguments["discount_percentage"]),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"simulate:{context.tenant_id}:{digest}"
