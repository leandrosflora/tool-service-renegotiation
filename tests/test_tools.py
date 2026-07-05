import json
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from app.config import Settings
from app.mcp_server import create_mcp_server
from app.renegotiation_client import RenegotiationServiceUnavailableError


class FakeClient:
    def __init__(self, responses: dict | None = None, fail: bool = False) -> None:
        self._responses = responses or {}
        self._fail = fail

    async def _resolve(self, key: str) -> dict:
        if self._fail:
            raise RenegotiationServiceUnavailableError("unavailable")
        return self._responses.get(key, {})

    async def get_client(self, cpf: str) -> dict:
        return await self._resolve("get_client")

    async def get_contracts(self, client_id: str) -> dict:
        return await self._resolve("get_contracts")

    async def get_debts(self, contract_id: str) -> dict:
        return await self._resolve("get_debts")

    async def check_eligibility(self, contract_id: str) -> dict:
        return await self._resolve("check_eligibility")

    async def simulate_proposal(self, contract_id: str, params: dict) -> dict:
        return await self._resolve("simulate_proposal")

    async def confirm_agreement(self, simulation_id: str) -> dict:
        return await self._resolve("confirm_agreement")

    async def get_document(self, agreement_id: str) -> dict:
        return await self._resolve("get_document")


def make_settings() -> Settings:
    return Settings()


async def call(mcp, name: str, args: dict) -> dict:
    result = await mcp.call_tool(name, args)
    return json.loads(result[0].text)


async def test_all_tools_registered_with_schema():
    mcp = create_mcp_server(make_settings(), FakeClient(), MagicMock())

    tools = await mcp.list_tools()

    names = {t.name for t in tools}
    assert names == {
        "consultar_cliente",
        "consultar_contratos",
        "consultar_debitos",
        "validar_elegibilidade",
        "simular_proposta",
        "confirmar_acordo",
        "gerar_documento",
    }
    for tool in tools:
        assert tool.description
        assert tool.inputSchema


async def test_consultar_cliente_success():
    client = FakeClient(responses={"get_client": {"name": "Maria"}})
    mcp = create_mcp_server(make_settings(), client, MagicMock())

    result = await call(mcp, "consultar_cliente", {"cpf": "12345678900"})

    assert result == {"name": "Maria"}


async def test_consultar_contratos_success():
    client = FakeClient(responses={"get_contracts": {"contracts": ["c1"]}})
    mcp = create_mcp_server(make_settings(), client, MagicMock())

    result = await call(mcp, "consultar_contratos", {"client_id": "client-1"})

    assert result == {"contracts": ["c1"]}


async def test_consultar_debitos_success():
    client = FakeClient(responses={"get_debts": {"debts": [1]}})
    mcp = create_mcp_server(make_settings(), client, MagicMock())

    result = await call(mcp, "consultar_debitos", {"contract_id": "contract-1"})

    assert result == {"debts": [1]}


async def test_validar_elegibilidade_success():
    client = FakeClient(responses={"check_eligibility": {"eligible": True}})
    mcp = create_mcp_server(make_settings(), client, MagicMock())

    result = await call(mcp, "validar_elegibilidade", {"contract_id": "contract-1"})

    assert result == {"eligible": True}


async def test_simular_proposta_success():
    client = FakeClient(responses={"simulate_proposal": {"simulation_id": "sim-1"}})
    mcp = create_mcp_server(make_settings(), client, MagicMock())

    result = await call(mcp, "simular_proposta", {"contract_id": "contract-1", "installments": 12})

    assert result == {"simulation_id": "sim-1"}


async def test_confirmar_acordo_success():
    client = FakeClient(responses={"confirm_agreement": {"agreement_id": "agr-1"}})
    mcp = create_mcp_server(make_settings(), client, MagicMock())

    result = await call(mcp, "confirmar_acordo", {"simulation_id": "sim-1"})

    assert result == {"agreement_id": "agr-1"}


async def test_gerar_documento_success():
    client = FakeClient(responses={"get_document": {"document_url": "http://x"}})
    mcp = create_mcp_server(make_settings(), client, MagicMock())

    result = await call(mcp, "gerar_documento", {"agreement_id": "agr-1"})

    assert result == {"document_url": "http://x"}


@pytest.mark.parametrize(
    "tool_name,args",
    [
        ("consultar_cliente", {"cpf": "12345678900"}),
        ("consultar_contratos", {"client_id": "client-1"}),
        ("consultar_debitos", {"contract_id": "contract-1"}),
        ("validar_elegibilidade", {"contract_id": "contract-1"}),
        ("simular_proposta", {"contract_id": "contract-1", "installments": 12}),
        ("confirmar_acordo", {"simulation_id": "sim-1"}),
        ("gerar_documento", {"agreement_id": "agr-1"}),
    ],
)
async def test_tool_propagates_error_when_service_unavailable(tool_name: str, args: dict):
    mcp = create_mcp_server(make_settings(), FakeClient(fail=True), MagicMock())

    with pytest.raises(ToolError):
        await mcp.call_tool(tool_name, args)
