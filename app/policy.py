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
        # conversation-orchestrator's JourneyStageTransitions now allows HandoffRequested ->
        # IdentificationPending on a fresh RequestedRenegotiation trigger, so a customer whose
        # conversation was previously handed off can be picked back up by the bot if no human ever
        # took over. That reopening turn is still signed with the *old* journey_stage
        # (HandoffRequested) since the stage claim reflects the turn's start, not the transition
        # that will be persisted after it completes - without this, consultar_cliente would always
        # be denied on that exact turn, the agent would fail to look the customer up, and would
        # likely recommend handoff again, permanently re-locking the conversation.
        "HandoffRequested",
    },
    "consultar_contratos": {
        # IdentificationPending is included alongside CustomerIdentified onward because the
        # journey_stage claim is signed once per agent turn (see agent-runtime-renegotiation's
        # tool_service.py) and never advances mid-turn - the orchestrator only persists the
        # CustomerIdentified transition after the whole turn completes. Without it, the natural
        # same-turn chain "consultar_cliente identifies them -> consultar_contratos lists their
        # contracts" is always denied on the second call, since the stage at signing time still
        # reflects the turn's start. consultar_contratos itself requires a client_id that can
        # only come from a consultar_cliente call already made from this stage, so this doesn't
        # weaken the identification requirement - it just lets both calls land in one turn.
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
        "ContractSelected",
        "EligibilityChecked",
        "SimulationParametersPending",
        "ProposalAvailable",
        "ProposalSelected",
        "ConfirmationPending",
    },
    "validar_elegibilidade": {
        "ContractSelected",
        "EligibilityChecked",
        "SimulationParametersPending",
    },
    "gerar_documento": {
        "AgreementConfirmed",
        "DocumentAvailable",
        "Completed",
    },
}

SIMULATION_STAGES = {
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
