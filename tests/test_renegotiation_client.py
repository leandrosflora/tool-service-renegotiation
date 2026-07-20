import pytest
import respx
from httpx import Response

from app.config import Settings
from app.renegotiation_client import RenegotiationServiceClient, RenegotiationServiceUnavailableError
from app.platform import ToolExecutionContext

BASE_URL = "http://renegotiation.test"
TENANT_ID = "00000000-0000-0000-0000-000000000001"


def make_client(retry_attempts: int = 1) -> RenegotiationServiceClient:
    settings = Settings(
        renegotiation_service_base_url=BASE_URL,
        renegotiation_service_retry_attempts=retry_attempts,
        internal_auth_signing_key="test-only-internal-auth-signing-key-32-bytes-min",
    )
    return RenegotiationServiceClient(settings)


def _context(*, journey_stage: str = "CustomerIdentified") -> ToolExecutionContext:
    return ToolExecutionContext(
        tenant_id=TENANT_ID,
        caller_service="agent-runtime-renegotiation",
        conversation_id="conversation-1",
        message_id="wamid-1",
        journey_stage=journey_stage,
        journey_version=0,
        confirmation_message_id=None,
    )


@pytest.fixture(autouse=True)
def execution_context(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.renegotiation_client as module

    monkeypatch.setattr(module, "current_tenant_id", lambda: TENANT_ID)
    monkeypatch.setattr(module, "current_execution_context", _context)


@respx.mock
async def test_get_client_success():
    respx.get(f"{BASE_URL}/clients/12345678900").mock(
        return_value=Response(200, json={"name": "Maria"})
    )

    result = await make_client().get_client("12345678900")

    assert result == {"name": "Maria"}


@respx.mock
async def test_get_contracts_success():
    respx.get(f"{BASE_URL}/clients/client-1/contracts").mock(
        return_value=Response(200, json={"contracts": ["c1", "c2"]})
    )

    result = await make_client().get_contracts("client-1")

    assert result == {"contracts": ["c1", "c2"]}


@respx.mock
async def test_get_debts_success():
    respx.get(f"{BASE_URL}/contracts/contract-1/debts").mock(
        return_value=Response(200, json={"debts": [{"amount": 100}]})
    )

    result = await make_client().get_debts("contract-1")

    assert result == {"debts": [{"amount": 100}]}


@respx.mock
async def test_check_eligibility_success():
    respx.get(f"{BASE_URL}/contracts/contract-1/eligibility").mock(
        return_value=Response(200, json={"eligible": True})
    )

    result = await make_client().check_eligibility("contract-1")

    assert result == {"eligible": True}


@respx.mock
async def test_simulate_proposal_success():
    respx.post(f"{BASE_URL}/contracts/contract-1/simulations").mock(
        return_value=Response(200, json={"simulation_id": "sim-1"})
    )

    result = await make_client().simulate_proposal(
        "contract-1", {"installments": 12}, "idem-simulate-1"
    )

    assert result == {"simulation_id": "sim-1"}


@respx.mock
async def test_confirm_agreement_success():
    respx.post(f"{BASE_URL}/simulations/sim-1/confirmations").mock(
        return_value=Response(200, json={"agreement_id": "agr-1"})
    )

    result = await make_client().confirm_agreement("sim-1", "idem-confirm-1")

    assert result == {"agreement_id": "agr-1"}


@respx.mock
async def test_get_document_success():
    respx.get(f"{BASE_URL}/agreements/agr-1/document").mock(
        return_value=Response(200, json={"document_url": "http://docs/agr-1.pdf"})
    )

    result = await make_client().get_document("agr-1")

    assert result == {"document_url": "http://docs/agr-1.pdf"}


@respx.mock
async def test_transient_failure_then_success_recovers_on_retry():
    route = respx.get(f"{BASE_URL}/clients/12345678900")
    route.side_effect = [Response(503), Response(200, json={"name": "Maria"})]

    result = await make_client(retry_attempts=2).get_client("12345678900")

    assert result == {"name": "Maria"}
    assert route.call_count == 2


@respx.mock
async def test_persistent_failure_raises_unavailable_error():
    respx.get(f"{BASE_URL}/clients/12345678900").mock(return_value=Response(503))

    with pytest.raises(RenegotiationServiceUnavailableError):
        await make_client(retry_attempts=1).get_client("12345678900")
