from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

import httpx
from tenacity import retry, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)


class RenegotiationServiceUnavailableError(Exception):
    """Raised when the Renegotiation Service cannot be reached after retries are exhausted."""


class RenegotiationServiceClient:
    """One resilient HTTP client shared by all seven governed tools."""

    def __init__(self, base_url: str, retry_attempts: int, timeout: float = 5.0) -> None:
        self._base_url = base_url
        self._retry_attempts = retry_attempts
        self._timeout = timeout

    async def get_client(self, cpf: str) -> dict[str, Any]:
        return await self._get(f"/clients/{cpf}")

    async def get_contracts(self, client_id: str) -> dict[str, Any]:
        return await self._get(f"/clients/{client_id}/contracts")

    async def get_debts(self, contract_id: str) -> dict[str, Any]:
        return await self._get(f"/contracts/{contract_id}/debts")

    async def check_eligibility(self, contract_id: str) -> dict[str, Any]:
        return await self._get(f"/contracts/{contract_id}/eligibility")

    async def simulate_proposal(self, contract_id: str, params: dict[str, Any]) -> dict[str, Any]:
        return await self._post(f"/contracts/{contract_id}/simulations", params)

    async def confirm_agreement(self, simulation_id: str) -> dict[str, Any]:
        return await self._post(f"/simulations/{simulation_id}/confirmations", {})

    async def get_document(self, agreement_id: str) -> dict[str, Any]:
        return await self._get(f"/agreements/{agreement_id}/document")

    async def _get(self, path: str) -> dict[str, Any]:
        return await self._call_with_retry(lambda client: client.get(path))

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._call_with_retry(lambda client: client.post(path, json=body))

    async def _call_with_retry(
        self, request_fn: Callable[[httpx.AsyncClient], Awaitable[httpx.Response]]
    ) -> dict[str, Any]:
        @retry(stop=stop_after_attempt(self._retry_attempts + 1), wait=wait_fixed(0.2), reraise=True)
        async def _call() -> dict[str, Any]:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
                response = await request_fn(client)
                response.raise_for_status()
                return response.json()

        try:
            return await _call()
        except Exception as exc:
            # Log only the exception type, not its message/args: httpx exceptions
            # embed the request URL (which contains CPF/contract identifiers) in
            # their string representation, and exc_info would leak that into logs.
            logger.warning("Renegotiation Service call failed after retries (%s)", type(exc).__name__)
            raise RenegotiationServiceUnavailableError(
                "Renegotiation Service unavailable after retries"
            ) from exc
