from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.rest_api import create_rest_api
from tests.test_tools import FakeClient, authorize


def make_client(fake: FakeClient) -> TestClient:
    app = create_rest_api(Settings(), fake, MagicMock())
    return TestClient(app, raise_server_exceptions=False)


def test_swagger_ui_is_served():
    client = make_client(FakeClient())

    response = client.get("/docs")

    assert response.status_code == 200


def test_openapi_schema_lists_all_seven_operations():
    client = make_client(FakeClient())

    schema = client.get("/openapi.json").json()

    paths = schema["paths"]
    assert set(paths) == {
        "/clients/{cpf}",
        "/clients/{client_id}/contracts",
        "/contracts/{contract_id}/debts",
        "/contracts/{contract_id}/eligibility",
        "/contracts/{contract_id}/simulations",
        "/simulations/{simulation_id}/confirmations",
        "/agreements/{agreement_id}/document",
    }


def test_consultar_cliente_success(monkeypatch: pytest.MonkeyPatch):
    authorize(monkeypatch, journey_stage="CustomerIdentified")
    client = make_client(FakeClient(responses={"get_client": {"name": "Maria"}}))

    response = client.get("/clients/12345678900")

    assert response.status_code == 200
    assert response.json() == {"name": "Maria"}


def test_simular_proposta_success(monkeypatch: pytest.MonkeyPatch):
    authorize(monkeypatch, journey_stage="ContractSelected")
    client = make_client(FakeClient(responses={"simulate_proposal": {"simulation_id": "sim-1"}}))

    response = client.post("/contracts/contract-1/simulations", json={"installments": 12})

    assert response.status_code == 200
    assert response.json() == {"simulation_id": "sim-1"}


def test_consultar_cliente_propagates_error_when_service_unavailable():
    client = make_client(FakeClient(fail=True))

    response = client.get("/clients/12345678900")

    assert response.status_code == 500
