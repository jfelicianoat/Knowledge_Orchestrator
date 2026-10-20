"""AI OS Core como director: pide permiso antes de mandar trabajo al Broker.

Core es el plano de control del ecosistema del TFM. Esta app no lo necesita: sin
``KO_CORE_URL`` todo sigue igual. Con él, ``BrokerClient.create_task`` evalúa antes la
política ``knowledge_orchestrator:broker`` y solo envía con un ALLOW ejecutable:

- una denegación es un fallo permanente de esa tarea (``CORE_DENIED``), visible en la app;
- si Core no contesta la tarea **no se envía** y se reintenta con el backoff de siempre:
  quien configuró un director no quiere que se le salte cuando se cae;
- cada tarea deja recibos en Core con su clave de idempotencia (``accepted`` al enviarla
  y el estado terminal al verla terminar), para que tras una caída Core sepa si se puede
  reenviar o ya está hecha.
"""
from __future__ import annotations

import contextlib
import re
import time
from typing import Any

import httpx

POLICY_SCOPE = "knowledge_orchestrator:broker"
#: Cómo se presenta esta app ante Core (debe coincidir con su token por app).
PRINCIPAL = "knowledge_orchestrator"
ENV_CORE_URL = "KO_CORE_URL"
ENV_CORE_TOKEN = "KO_CORE_TOKEN"

TERMINAL_RECEIPTS = {"completed": "succeeded", "failed": "failed_terminal", "cancelled": "cancelled"}
#: Un salto para el monitor de Core nunca debe hacer esperar a la tarea.
HOP_TIMEOUT_SECONDS = 3.0


def flow_id_for(operation_id: str) -> str:
    """El flujo del monitor de Core para una tarea: su clave de idempotencia, en un formato que Core acepta."""
    return re.sub(r"[^A-Za-z0-9_.:\-]", "_", operation_id)[:128] or "ko"


class CoreUnavailable(RuntimeError):
    """Core no contestó o devolvió un error: por seguridad no se envía nada."""


class CoreDenied(RuntimeError):
    """Core contestó, pero no autoriza el envío."""


class KoCoreGate:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("KO_CORE_URL debe ser una URL http o https")
        headers = {"Accept": "application/json", "X-Principal-Id": PRINCIPAL}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._base_url = base_url.rstrip("/")
        self._headers = headers
        self._transport = transport
        #: Cuándo salió cada tarea hacia el Broker (latencia en el monitor de Core).
        self._sent_at: dict[str, float] = {}

    async def authorize(self, payload: dict[str, Any]) -> int | None:
        """Lanza sin ALLOW ejecutable; si no, el turno en la cola del Broker que el director
        fijó a KO en el monitor (None = sin fijar)."""
        risk = _mapping(payload.get("risk"))
        metadata = _mapping(_mapping(payload.get("content")).get("metadata"))
        decision = await self._post("/api/v1/policies/evaluate", {
            "scope": POLICY_SCOPE,
            "principal_id": PRINCIPAL,
            "resource_id": str(payload.get("idempotency_key") or ""),
            "context": {
                "operation_type": str(metadata.get("purpose") or "knowledge_task"),
                # La que ya declara la petición al Broker; sin ella, lo prudente
                "data_classification": str(risk.get("data_classification") or "confidential"),
                "flow_id": flow_id_for(str(payload.get("idempotency_key") or "")),
            },
        })
        if decision.get("authorization") != "ALLOW" or decision.get("executable") is not True:
            raise CoreDenied(_denied_text(decision))
        priority = decision.get("broker_priority")
        return priority if isinstance(priority, int) else None

    async def receipt(self, operation_id: str, broker_status: str, task_id: str) -> None:
        """Un recibo perdido no tumba la tarea: Core verá el siguiente estado."""
        status = TERMINAL_RECEIPTS.get(broker_status) or ("accepted" if broker_status == "accepted" else "in_progress")
        flow = flow_id_for(operation_id)
        with contextlib.suppress(CoreUnavailable):
            await self._post("/api/v1/operations/receipts", {
                "operation_id": operation_id,
                "receiver_service": "ai_broker",
                "status": status,
                "evidence": {"task_id": task_id, "flow_id": flow},
            })
        # Monitor de Core: el envío es la petición al Broker; el estado terminal, su respuesta
        if status == "accepted":
            self._sent_at[operation_id] = time.monotonic()
            await self.hop(flow, "request", "tarea de conocimiento", {"task_id": task_id})
        elif broker_status in TERMINAL_RECEIPTS:
            details: dict[str, Any] = {"task_id": task_id, "status": broker_status}
            began = self._sent_at.pop(operation_id, None)
            if began is not None:
                details["latency_ms"] = int((time.monotonic() - began) * 1000)
            await self.hop(flow, "response" if status == "succeeded" else "error", broker_status, details)

    async def hop(self, flow_id: str, kind: str, summary: str = "", details: dict[str, Any] | None = None) -> None:
        """Cuenta al monitor de Core lo que se manda al Broker. Enviar y olvidar."""
        body = {"flow_id": flow_id, "source_system": PRINCIPAL, "target_system": "ai_broker",
                "kind": kind, "summary": summary[:200], "details": details or {}}
        with contextlib.suppress(Exception):  # el monitor es secundario: jamás para una tarea
            async with httpx.AsyncClient(
                base_url=self._base_url, headers=self._headers, timeout=HOP_TIMEOUT_SECONDS,
                transport=self._transport,
            ) as client:
                await client.post("/api/v1/flows/hops", json=body)

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, headers=self._headers, timeout=10.0, transport=self._transport
            ) as client:
                response = await client.post(path, json=body)
        except httpx.HTTPError as error:
            raise CoreUnavailable(f"No se pudo consultar a AI OS Core: {error}") from error
        if response.status_code >= 400:
            raise CoreUnavailable(f"AI OS Core respondió {response.status_code}: {response.text[:300]}")
        result: dict[str, Any] = response.json()
        return result


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _denied_text(decision: dict[str, Any]) -> str:
    authorization = decision.get("authorization")
    if authorization == "REQUIRE_APPROVAL":
        return f"AI OS Core pide una aprobación humana antes de enviar esto (políticas de «{POLICY_SCOPE}»)."
    if authorization == "INDETERMINATE":
        missing = ", ".join(decision.get("unknown_inputs") or []) or "algún dato"
        return f"AI OS Core no puede decidir (le falta: {missing}); por seguridad no se envía."
    return f"AI OS Core no autoriza este envío ({authorization}). Revisa las políticas de «{POLICY_SCOPE}»."
