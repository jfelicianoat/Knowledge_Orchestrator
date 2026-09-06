from __future__ import annotations

from typing import Any

import httpx

from knowledge_orchestrator.config import BrokerSettings
from knowledge_orchestrator.domain.broker_contracts import (
    normalize_capabilities_response,
    validate_accepted_response,
    validate_artifacts_response,
    validate_create_task_request,
    validate_invocations_response,
    validate_models_response,
    validate_task_status_response,
)


class BrokerClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class TransientBrokerError(BrokerClientError):
    pass


class PermanentBrokerError(BrokerClientError):
    pass


class BrokerClient:
    # Un 401/403 suele significar que el token admin rotó al reiniciarse el
    # Broker. No invalida las tareas persistidas y debe poder recuperarse.
    TRANSIENT_STATUSES = {401, 403, 429, 502, 503, 504}

    def __init__(
        self,
        settings: BrokerSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self._client: httpx.AsyncClient | None = None
        # Lo último que anunció el Broker. Gobierna qué campos opcionales del
        # contrato 2.10 se pueden enviar: su validación es `extra="forbid"`, así
        # que un campo que ese Broker no tiene no se ignora, hace fallar la
        # petición entera con 422 y se lleva por delante la tarea.
        self._capabilities: dict[str, Any] = {}

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

    async def reconfigure(self, settings: BrokerSettings) -> None:
        """Cambia endpoint y credencial sin reutilizar conexiones con cabeceras antiguas."""

        await self.close()
        self.settings = settings
        # Otro Broker puede anunciar otro contrato: conservar lo que prometía el
        # anterior haría que se le enviasen campos que no admite.
        self._capabilities = {}

    async def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_create_task_request(payload)
        payload = self._strip_unsupported_fields(payload)
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

    def _strip_unsupported_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Quita los campos que este Broker no anuncia (Client_API.md, 5.1).

        La validación del Broker es estricta: un campo que no exista en su
        contrato hace fallar la petición con 422, no se ignora. Enviar
        `auxiliary_invocations` a un Broker anterior al 2.10 mataría la tarea
        entera por pedir una garantía adicional, que es el peor intercambio
        posible. Sin el opt-out queda la garantía implícita (`target_model` con
        `fallback_allowed: false`), y si tampoco la hay, el sondeo ocurre: eso
        se ve en la telemetría, no se supone.
        """
        if "auxiliary_invocations" not in payload:
            return payload
        if self._capabilities.get("auxiliary_invocations_optout") is True:
            return payload
        filtered = dict(payload)
        filtered.pop("auxiliary_invocations", None)
        return filtered

    async def invocations(self, task_id: str) -> list[dict[str, Any]]:
        """Telemetría por invocación (contrato 2.10, 8.1).

        Bajo un mismo `task_id` conviven las llamadas que ejecutan la tarea y
        las que el Broker lanza por su cuenta para medir su catálogo. Quien
        necesite separarlas debe usar `is_contractual_invocation`, nunca una
        lista negra de nombres de rol.
        """
        response = await self._request("GET", f"/api/v1/tasks/{task_id}/invocations")
        if response.status_code != 200:
            self._raise_for_status(response)
        return [dict(item) for item in validate_invocations_response(self._json(response), task_id)]

    async def artifacts(self, task_id: str) -> list[dict[str, Any]]:
        """Ficheros que produjo la tarea (contrato 2.10, 8.3).

        Es la vía canónica para recoger el entregable: viene tipado y con su
        `sha256` sobre los bytes exactos. `result.assistant_content` sigue
        sirviendo para enseñar la respuesta, pero `result` no tiene esquema en
        el OpenAPI y no va a tenerlo.
        """
        response = await self._request("GET", f"/api/v1/tasks/{task_id}/artifacts")
        if response.status_code != 200:
            self._raise_for_status(response)
        return [dict(item) for item in validate_artifacts_response(self._json(response), task_id)]

    async def download_artifact(self, task_id: str, artifact_id: str) -> bytes:
        """Bytes de un artefacto por su `download_url` (contrato 2.10, 8.3).

        Un `410` no es un `404`: la fila existe y el fichero ya no —lo podó la
        retención, o se restauró una copia sin `state/tasks`—. Existió y se
        borró a propósito, que no es lo mismo que no haber existido nunca.
        """
        response = await self._request("GET", f"/api/v1/tasks/{task_id}/artifacts/{artifact_id}")
        if response.status_code != 200:
            self._raise_for_status(response)
        return response.content

    async def cancel_task(self, task_id: str, *, cancel_url: str | None = None) -> dict[str, Any]:
        response = await self._request("DELETE", cancel_url or f"/api/v1/tasks/{task_id}")
        if response.status_code not in {200, 202}:
            self._raise_for_status(response)
        return dict(validate_task_status_response(self._json(response), task_id))

    async def list_models(self) -> list[dict[str, Any]]:
        response = await self._request("GET", "/api/v1/models")
        if response.status_code != 200:
            self._raise_for_status(response)
        return [dict(model) for model in validate_models_response(self._json(response))]

    async def capabilities(self) -> dict[str, Any]:
        response = await self._request("GET", "/api/v1/capabilities")
        if response.status_code != 200:
            self._raise_for_status(response)
        # Capabilities es aditivo: se ignoran campos desconocidos y la versión
        # se expone al worker para advertir, sin bloquear el envío de tareas.
        normalized = normalize_capabilities_response(self._json(response))
        self._capabilities = dict(normalized)
        return normalized

    async def health(self) -> dict[str, Any]:
        response = await self._request("GET", "/health")
        if response.status_code != 200:
            self._raise_for_status(response)
        return dict(self._json(response))

    async def auth_check(self) -> dict[str, Any]:
        """Valida la credencial en el endpoint contractual, nunca mediante health."""
        response = await self._request("GET", "/api/v1/auth/check")
        if response.status_code != 200:
            self._raise_for_status(response)
        data = self._json(response)
        if not isinstance(data.get("authenticated"), bool) or not isinstance(data.get("auth_required"), bool):
            raise PermanentBrokerError("El Broker devolvió una validación de credencial inválida")
        return dict(data)

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
        code: str | None = None
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = body.get("detail")
                nested = body.get("error")
                if isinstance(detail, dict):
                    nested = detail
                if isinstance(nested, dict):
                    raw_code = nested.get("code")
                    code = str(raw_code) if raw_code else None
                    message = str(
                        nested.get("message") or nested.get("code") or body.get("message") or message
                    )
                else:
                    raw_code = body.get("code")
                    code = str(raw_code) if raw_code else None
                    message = str(
                        body.get("error_message") or body.get("message") or body.get("code") or message
                    )
        except ValueError:
            pass
        if response.status_code in self.TRANSIENT_STATUSES:
            raise TransientBrokerError(message, status_code=response.status_code, code=code)
        raise PermanentBrokerError(message, status_code=response.status_code, code=code)
