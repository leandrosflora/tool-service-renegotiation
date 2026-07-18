from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

import httpx
from tenacity import retry, stop_after_attempt, wait_fixed

from app.config import Settings
from app.platform import create_service_token, current_tenant_id

logger = logging.getLogger(__name__)


class RenegotiationServiceUnavailableError(Exception):
    """Raised when the Renegotiation Service cannot be reached."""


class RenegotiationServiceClient:
    def __init__(self, settings: Settings, timeout: float = 5.0) -> None:
        self._settings = settings
        self._base_url = settings.renegotiation_service_base_url
        self._retry_attempts = settings.renegotiation_service_retry_attempts
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
        return await self._post(
            f"/simulations/{simulation_id}/confirmations",
            {},
            idempotency_key=f"confirm-agreement:{simulation_id}",
        )

    async def get_document(self, agreement_id: str) -> dict[str, Any]:
        return await self._get(f"/agreements/{agreement_id}/document")

    async def _get(self, path: str) -> dict[str, Any]:
        @retry(stop=stop_after_attempt(self._retry_attempts + 1), wait=wait_fixed(0.2), reraise=True)
        async def _call() -> dict[str, Any]:
            return await self._execute(lambda client: client.get(path))

        try:
            return await _call()
        except Exception as exc:
            self._raise_unavailable(exc, "after retries")

    async def _post(
        self,
        path: str,
        body: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        request_headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        try:
            return await self._execute(
                lambda client: client.post(path, json=body, headers=request_headers)
            )
        except Exception as exc:
            self._raise_unavailable(exc, "without retry")

    async def _execute(
        self,
        request_fn: Callable[[httpx.AsyncClient], Awaitable[httpx.Response]],
    ) -> dict[str, Any]:
        token = create_service_token(self._settings, self._settings.renegotiation_service_audience)
        headers = {"Authorization": f"Bearer {token}"}
        tenant_id = current_tenant_id()
        if tenant_id:
            headers["X-Tenant-Id"] = tenant_id

        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            headers=headers,
        ) as client:
            response = await request_fn(client)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _raise_unavailable(exc: Exception, retry_context: str) -> None:
        logger.warning(
            "Renegotiation Service call failed %s (%s)",
            retry_context,
            type(exc).__name__,
        )
        raise RenegotiationServiceUnavailableError(
            "Renegotiation Service unavailable"
        ) from exc
