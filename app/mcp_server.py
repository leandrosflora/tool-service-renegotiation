from __future__ import annotations

from confluent_kafka import Producer
from mcp.server.fastmcp import FastMCP

from app.config import Settings
from app.events.instrumentation import with_tool_event
from app.renegotiation_client import RenegotiationServiceClient


def create_mcp_server(settings: Settings, client: RenegotiationServiceClient, producer: Producer) -> FastMCP:
    """Builds the FastMCP server instance with the seven governed renegotiation tools
    registered as thin wrappers over the shared RenegotiationServiceClient, each
    instrumented to publish a tool.executed event regardless of outcome."""

    mcp = FastMCP(
        name="tool-service-renegotiation",
        host=settings.mcp_host,
        port=settings.mcp_port,
    )

    @mcp.tool(description="Consulta os dados cadastrais do cliente pelo CPF.")
    @with_tool_event("consultar_cliente", producer, settings)
    async def consultar_cliente(cpf: str) -> dict:
        return await client.get_client(cpf)

    @mcp.tool(description="Consulta os contratos de um cliente.")
    @with_tool_event("consultar_contratos", producer, settings)
    async def consultar_contratos(client_id: str) -> dict:
        return await client.get_contracts(client_id)

    @mcp.tool(description="Consulta os debitos em aberto de um contrato.")
    @with_tool_event("consultar_debitos", producer, settings)
    async def consultar_debitos(contract_id: str) -> dict:
        return await client.get_debts(contract_id)

    @mcp.tool(description="Valida a elegibilidade de um contrato para renegociacao.")
    @with_tool_event("validar_elegibilidade", producer, settings)
    async def validar_elegibilidade(contract_id: str) -> dict:
        return await client.check_eligibility(contract_id)

    @mcp.tool(description="Simula uma proposta de renegociacao para um contrato.")
    @with_tool_event("simular_proposta", producer, settings)
    async def simular_proposta(
        contract_id: str, installments: int, discount_percentage: float = 0.0
    ) -> dict:
        return await client.simulate_proposal(
            contract_id, {"installments": installments, "discount_percentage": discount_percentage}
        )

    @mcp.tool(description="Confirma e formaliza um acordo a partir de uma simulacao.")
    @with_tool_event("confirmar_acordo", producer, settings)
    async def confirmar_acordo(simulation_id: str) -> dict:
        return await client.confirm_agreement(simulation_id)

    @mcp.tool(description="Gera o documento/comprovante de um acordo formalizado.")
    @with_tool_event("gerar_documento", producer, settings)
    async def gerar_documento(agreement_id: str) -> dict:
        return await client.get_document(agreement_id)

    return mcp
