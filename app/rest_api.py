from __future__ import annotations

from confluent_kafka import Producer
from fastapi import FastAPI
from pydantic import BaseModel

from app.config import Settings
from app.events.instrumentation import with_tool_event
from app.renegotiation_client import RenegotiationServiceClient


class SimulationRequest(BaseModel):
    installments: int
    discount_percentage: float = 0.0


def create_rest_api(settings: Settings, client: RenegotiationServiceClient, producer: Producer) -> FastAPI:
    """Documentation-only REST/Swagger facade over the same seven governed tools exposed
    via MCP in mcp_server.py. agent-runtime-renegotiation talks to this service over MCP
    (mcp_port), never over this port - this exists purely so the tools have Swagger UI,
    since FastMCP's streamable-HTTP transport has no OpenAPI surface of its own."""

    app = FastAPI(
        title="tool-service-renegotiation (REST docs)",
        description=(
            "Documentation-only REST mirror of the MCP tools served at the streamable-HTTP "
            "MCP endpoint (see TOOL_SERVICE_MCP_URL). Not consumed by any service in this "
            "workspace - agent-runtime-renegotiation is an MCP client, not a REST client."
        ),
    )

    @app.get("/clients/{cpf}", summary="Consulta os dados cadastrais do cliente pelo CPF")
    @with_tool_event("consultar_cliente", producer, settings)
    async def consultar_cliente(cpf: str) -> dict:
        return await client.get_client(cpf)

    @app.get("/clients/{client_id}/contracts", summary="Consulta os contratos de um cliente")
    @with_tool_event("consultar_contratos", producer, settings)
    async def consultar_contratos(client_id: str) -> dict:
        return await client.get_contracts(client_id)

    @app.get("/contracts/{contract_id}/debts", summary="Consulta os debitos em aberto de um contrato")
    @with_tool_event("consultar_debitos", producer, settings)
    async def consultar_debitos(contract_id: str) -> dict:
        return await client.get_debts(contract_id)

    @app.get("/contracts/{contract_id}/eligibility", summary="Valida a elegibilidade de um contrato para renegociacao")
    @with_tool_event("validar_elegibilidade", producer, settings)
    async def validar_elegibilidade(contract_id: str) -> dict:
        return await client.check_eligibility(contract_id)

    @app.post("/contracts/{contract_id}/simulations", summary="Simula uma proposta de renegociacao para um contrato")
    @with_tool_event("simular_proposta", producer, settings)
    async def simular_proposta(contract_id: str, body: SimulationRequest) -> dict:
        return await client.simulate_proposal(
            contract_id,
            {"installments": body.installments, "discount_percentage": body.discount_percentage},
        )

    @app.post("/simulations/{simulation_id}/confirmations", summary="Confirma e formaliza um acordo a partir de uma simulacao")
    @with_tool_event("confirmar_acordo", producer, settings)
    async def confirmar_acordo(simulation_id: str) -> dict:
        return await client.confirm_agreement(simulation_id)

    @app.get("/agreements/{agreement_id}/document", summary="Gera o documento/comprovante de um acordo formalizado")
    @with_tool_event("gerar_documento", producer, settings)
    async def gerar_documento(agreement_id: str) -> dict:
        return await client.get_document(agreement_id)

    return app
