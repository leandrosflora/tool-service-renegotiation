import asyncio
from unittest.mock import MagicMock

import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.config import Settings
from app.mcp_server import create_mcp_server
from app.renegotiation_client import RenegotiationServiceUnavailableError

TEST_PORT = 8491
TEST_URL = f"http://127.0.0.1:{TEST_PORT}/mcp"

EXPECTED_TOOL_NAMES = {
    "consultar_cliente",
    "consultar_contratos",
    "consultar_debitos",
    "validar_elegibilidade",
    "simular_proposta",
    "confirmar_acordo",
    "gerar_documento",
}


class FailingClient:
    async def _fail(self) -> dict:
        raise RenegotiationServiceUnavailableError("unavailable")

    async def get_client(self, cpf: str) -> dict:
        return await self._fail()

    async def get_contracts(self, client_id: str) -> dict:
        return await self._fail()

    async def get_debts(self, contract_id: str) -> dict:
        return await self._fail()

    async def check_eligibility(self, contract_id: str) -> dict:
        return await self._fail()

    async def simulate_proposal(self, contract_id: str, params: dict) -> dict:
        return await self._fail()

    async def confirm_agreement(self, simulation_id: str) -> dict:
        return await self._fail()

    async def get_document(self, agreement_id: str) -> dict:
        return await self._fail()


@pytest.fixture
async def running_server():
    settings = Settings(mcp_host="127.0.0.1", mcp_port=TEST_PORT)
    mcp = create_mcp_server(settings, FailingClient(), MagicMock())

    config = uvicorn.Config(
        mcp.streamable_http_app(), host="127.0.0.1", port=TEST_PORT, log_level="warning"
    )
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    while not server.started:
        await asyncio.sleep(0.05)

    try:
        yield TEST_URL
    finally:
        server.should_exit = True
        await server_task


async def test_client_can_connect_initialize_and_list_tools(running_server: str):
    async with streamable_http_client(running_server) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

    assert {t.name for t in tools.tools} == EXPECTED_TOOL_NAMES


async def test_server_survives_tool_failure_and_remains_usable(running_server: str):
    async with streamable_http_client(running_server) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool("consultar_cliente", {"cpf": "12345678900"})
            assert result.isError is True

            tools_after = await session.list_tools()
            assert len(tools_after.tools) == len(EXPECTED_TOOL_NAMES)
