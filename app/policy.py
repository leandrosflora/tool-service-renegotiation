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
    },
    "consultar_contratos": {
        "CustomerIdentified",
        "ContractSelectionPending",
        "ContractSelected",
        "EligibilityChecked",
        "SimulationParametersPending",
        "ProposalAvailable",
        "ProposalSelected",
        "ConfirmationPending",
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
