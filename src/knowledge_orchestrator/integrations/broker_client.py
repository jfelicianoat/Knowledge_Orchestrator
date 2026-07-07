from __future__ import annotations

from typing import Any

import httpx

from knowledge_orchestrator.config import BrokerSettings
from knowledge_orchestrator.domain.broker_contracts import (
    BrokerContractError,
    validate_accepted_response,
    validate_create_task_request,
    validate_models_response,
    validate_task_status_response,
)


class BrokerClientError(RuntimeError):
    pass


class TransientBrokerError(BrokerClientError):
    pass


class PermanentBrokerError(BrokerClientError):
    pass


class BrokerClient:
    TRANSIENT_STATUSES = {429, 502, 503, 504}

    def __init__(
        self,
        settings: BrokerSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        if self._client is None:
            headers = {"X-Admin-Token": self.settings.admin_token} if self.settings.admin_token else None
            self._client = httpx.AsyncClient(
                base_url=self.settings.base_url,
                timeout=self.settings.request_timeout_seconds,
                transport=self.transport,
                headers=headers,
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_create_task_request(payload)
        response = await self._request("POST", "/api/v1/tasks", json=payload)
        if response.status_code not in {200, 202}:
            self._raise_for_status(response)
        data = self._json(response)
        return dict(validate_accepted_response(data))

    async def get_task(
        self,
        task_id: str,
        *,
        status_url: str | None = None,
    ) -> dict[str, Any]:
        response = await self._request("GET", status_url or f"/api/v1/tasks/{task_id}")
        if response.status_code != 200:
            self._raise_for_status(response)
        data = self._json(response)
        return dict(validate_task_status_response(data, task_id))

    async def cancel_task(self, task_id: str, *, cancel_url: str | None = None) -> dict[str, Any]:
        response = await self._request("DELETE", cancel_url or f"/api/v1/tasks/{task_id}")
        if response.status_code not in {200, 202}:
            self._raise_for_status(response)
        return dict(self._json(response))

    async def list_models(self) -> list[dict[str, Any]]:
        response = await self._request("GET", "/api/v1/models")
        if response.status_code != 200:
            self._raise_for_status(response)
        return [dict(model) for model in validate_models_response(self._json(response))]

    async def health(self) -> dict[str, Any]:
        response = await self._request("GET", "/health")
        if response.status_code != 200:
            self._raise_for_status(response)
        return dict(self._json(response))

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        await self.start()
        assert self._client is not None
        try:
            return await self._client.request(method, url, **kwargs)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as error:
            raise TransientBrokerError(str(error)) from error

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as error:
            raise PermanentBrokerError("El Broker devolvió JSON inválido") from error
        if not isinstance(data, dict):
            raise PermanentBrokerError("El Broker debe devolver un objeto JSON")
        return data

    def _raise_for_status(self, response: httpx.Response) -> None:
        message = f"Broker HTTP {response.status_code}"
        try:
            body = response.json()
            if isinstance(body, dict):
                message = str(body.get("error_message") or body.get("message") or body.get("code") or message)
        except ValueError:
            pass
        if response.status_code in self.TRANSIENT_STATUSES:
            raise TransientBrokerError(message)
        raise PermanentBrokerError(message)
