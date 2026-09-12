"""Aplicación del estado que reporta el Broker, y cierre del workflow.

`apply_status` es la transición más delicada del sistema: llega en cualquier
momento, puede llegar dos veces y decide si un trabajo sigue, termina o falla.
Por eso está partida en piezas que se pueden leer y probar por separado —
traducción del estado, resultado, error, metadatos, avisos— mientras el método
público conserva **una sola transacción**: lo que se escribe, se escribe entero
o no se escribe.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from knowledge_orchestrator.domain.broker_models import TaskStatus
from knowledge_orchestrator.repositories.workflow_repository.control import ControlMixin
from knowledge_orchestrator.services.output_quality import study_notes_quality_error, study_notes_quality_message

#: Traducción del vocabulario del Broker al nuestro. Los estados terminales son
#: contrato; las fases intermedias pueden crecer de forma aditiva y todas
#: equivalen a «sigue trabajando», por eso lo desconocido cae en PROCESSING.
STATUS_MAP = {
    "queued": TaskStatus.QUEUED,
    # Contrato 2.8: esperas pasivas y autorrecuperables. Conservan el sitio
    # en cola; no ha empezado a ejecutar ni debe consumir reintentos.
    "waiting_for_memory": TaskStatus.QUEUED,
    "waiting_for_dependencies": TaskStatus.QUEUED,
    "processing": TaskStatus.PROCESSING,
    "routing": TaskStatus.PROCESSING,
    "planning": TaskStatus.PROCESSING,
    "resource_planning": TaskStatus.PROCESSING,
    "chunking": TaskStatus.PROCESSING,
    "generating": TaskStatus.PROCESSING,
    "proposing": TaskStatus.PROCESSING,
    "evaluating": TaskStatus.PROCESSING,
    "debating": TaskStatus.PROCESSING,
    "synthesizing": TaskStatus.PROCESSING,
    "verifying": TaskStatus.PROCESSING,
    # Estrategia agent del Broker esperando tool-calls del cliente; el
    # Orchestrator no envía tools, pero el estado es válido y no terminal.
    "waiting_for_tools": TaskStatus.PROCESSING,
    "completed": TaskStatus.SUCCESS,
    "success": TaskStatus.SUCCESS,
    "failed": TaskStatus.ERROR,
    "error": TaskStatus.ERROR,
    "cancel_requested": TaskStatus.CANCEL_REQUESTED,
    "cancelled": TaskStatus.CANCELLED,
}

#: El proveedor devolvió una respuesta vacía por quedarse sin presupuesto. Con
#: un modelo que razona, el razonamiento se come `max_output_tokens` y no queda
#: nada para la respuesta; el Broker lo dice con `done_reason=length`.
BUDGET_EXHAUSTED_CODES = frozenset({"INVALID_PROVIDER_RESPONSE"})
#: Techo del reintento automático. No se sube sin límite: un presupuesto enorme
#: convierte un fallo rápido en una espera larguísima con el mismo final.
BUDGET_CEILING = 16_000
#: Una sola ampliación automática. Si con el doble tampoco responde, el problema
#: es el modelo elegido y eso lo decide una persona, no un bucle.
MAX_BUDGET_RETRIES = 1


def presupuesto_agotado(error: dict[str, Any]) -> bool:
    """Distingue «se quedó sin tokens» de cualquier otro fallo del proveedor."""

    if str(error.get("code") or "") not in BUDGET_EXHAUSTED_CODES:
        return False
    mensaje = str(error.get("message") or "").lower()
    return "done_reason=length" in mensaje or "max_output_tokens" in mensaje


def ampliar_presupuesto(request: dict[str, Any], *, ceiling: int = BUDGET_CEILING) -> dict[str, Any] | None:
    """Duplica `max_output_tokens` sin pasar del techo. `None` si ya no cabe subir."""

    generation = request.get("generation")
    if not isinstance(generation, dict):
        return None
    actual = generation.get("max_output_tokens")
    if not isinstance(actual, int) or isinstance(actual, bool) or actual < 1:
        return None
    ampliado = min(actual * 2, max(ceiling, 1))
    if ampliado <= actual:
        return None
    copia = json.loads(json.dumps(request))
    copia["generation"]["max_output_tokens"] = ampliado
    return copia


#: Claves del resultado del Broker que se conservan como metadatos de la tarea.
CLAVES_METADATA = (
    "consensus", "scheduling", "usage", "model_used", "models_used",
    "arbiter_failures", "warnings", "agent", "long_context",
    "fallback_used", "inference_kind", "output_format",
)


def modelo_usado(broker_result: dict[str, Any] | None) -> Any:
    """El modelo que realmente respondió, según lo que anuncie el Broker.

    Se prefiere `model_used` y, si no viene, el último de `models_used`: en una
    estrategia de consenso el último es el que firma la respuesta final.
    """
    resultado = broker_result or {}
    anunciado = resultado.get("model_used")
    if isinstance(anunciado, dict):
        return anunciado.get("model")
    usados = resultado.get("models_used") or []
    if usados and isinstance(usados[-1], dict):
        return usados[-1].get("model")
    return None


def resultado_de(broker_result: dict[str, Any] | None) -> dict[str, Any]:
    """Normaliza el resultado a algo que siempre tenga `assistant_content`."""
    resultado = broker_result or {}
    if "assistant_content" in resultado:
        return dict(resultado)
    return {"assistant_content": resultado["result_markdown"], "broker_result": broker_result}


def error_de(payload: dict[str, Any]) -> dict[str, Any]:
    """Error normalizado. Un Broker que no explica el fallo no deja hueco."""
    bruto = payload.get("error") or {}
    return {
        "code": bruto.get("code", "BROKER_TASK_FAILED"),
        "message": bruto.get("message", bruto.get("code", "Broker task failed")),
        "retryable": bool(bruto.get("retryable", False)),
    }


def metadata_de(broker_result: dict[str, Any] | None) -> dict[str, Any]:
    resultado = broker_result or {}
    return {clave: resultado.get(clave) for clave in CLAVES_METADATA if clave in resultado}


class EstadoMixin(ControlMixin):
    """Transiciones de estado de una tarea y cierre de su workflow."""

    def apply_status(self, task_id: str, payload: dict[str, Any]) -> bool:
        """Aplica el estado reportado por el Broker. Devuelve si hubo cambio.

        Una tarea ya terminal no se reabre: devuelve `False` sin tocar nada, que
        es lo que hace idempotente recibir el mismo aviso dos veces.
        """
        target = STATUS_MAP.get(payload["status"], TaskStatus.PROCESSING)
        with self.database.transaction(immediate=True) as connection:
            current = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if current is None:
                raise ValueError("Tarea inexistente")
            if current["status"] in {"SUCCESS", "ERROR", "CANCELLED"}:
                return False
            # Una cancelación pedida no la borra un avance posterior del Broker:
            # el operador ya dijo que pare.
            if current["status"] == "CANCEL_REQUESTED" and target in {TaskStatus.QUEUED, TaskStatus.PROCESSING}:
                target = TaskStatus.CANCEL_REQUESTED

            broker_result = payload.get("result")
            error = error_de(payload) if target is TaskStatus.ERROR else {}
            if target is TaskStatus.SUCCESS and current["step_kind"] in {"SINGLE", "SYNTHESIS"}:
                result = resultado_de(broker_result)
                quality_code = study_notes_quality_error(result["assistant_content"], final=True)
                if quality_code:
                    target = TaskStatus.ERROR
                    error = {
                        "code": quality_code,
                        "message": study_notes_quality_message(quality_code),
                        "retryable": True,
                    }
            if target is TaskStatus.ERROR and self._reintentar_con_mas_presupuesto(
                connection, current, task_id, error
            ):
                return True
            self._escribir_tarea(connection, task_id, payload, target, broker_result, error)

            if target is TaskStatus.PROCESSING:
                self._marcar_captura_en_proceso(connection, current["capture_id"])
            elif target is TaskStatus.SUCCESS:
                self._cerrar_paso_con_exito(connection, current, task_id, broker_result)
            elif target in {TaskStatus.ERROR, TaskStatus.CANCELLED}:
                self._cerrar_paso_con_fallo(connection, current, task_id, target, error)
            return True

    def _reintentar_con_mas_presupuesto(
        self,
        connection: sqlite3.Connection,
        current: sqlite3.Row,
        task_id: str,
        error: dict[str, Any],
    ) -> bool:
        """Reabre la tarea con el doble de presupuesto cuando el modelo se quedó sin tokens.

        Es el único fallo del proveedor con una causa conocida y una solución
        mecánica. Quien usa la aplicación no tiene por qué saber qué es
        `done_reason=length`: se reintenta una vez y queda escrito en la
        cronología. La clave idempotente cambia porque el contenido cambia; con
        la misma clave y otro cuerpo el Broker respondería 409.
        """

        if not presupuesto_agotado(error):
            return False
        base_key = str(current["idempotency_key"]).split(":budget-", 1)[0]
        ampliaciones = str(current["idempotency_key"]).count(":budget-")
        if ampliaciones >= MAX_BUDGET_RETRIES:
            return False
        request = json.loads(current["request_json"])
        ampliado = ampliar_presupuesto(request, ceiling=BUDGET_CEILING)
        if ampliado is None:
            return False
        anterior = request["generation"]["max_output_tokens"]
        nuevo = ampliado["generation"]["max_output_tokens"]
        idempotency_key = f"{base_key}:budget-{ampliaciones + 1}"
        ampliado["idempotency_key"] = idempotency_key
        encoded = json.dumps(ampliado, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        connection.execute(
            "UPDATE tasks SET status = 'READY', request_json = ?, request_hash = ?, idempotency_key = ?, "
            "response_json = NULL, result_json = NULL, status_url = NULL, cancel_url = NULL, "
            "broker_task_id = NULL, error_code = NULL, error_message = NULL, error_retryable = NULL, "
            "next_retry_at = NULL, model_used = NULL, queued_at = NULL, started_at = NULL, "
            "completed_at = NULL, progress_json = '{}', "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE task_id = ?",
            (encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest(), idempotency_key, task_id),
        )
        connection.execute(
            "INSERT INTO events(capture_id, event_type, message, details_json) "
            "VALUES (?, 'BROKER_BUDGET_RETRY', ?, ?)",
            (
                current["capture_id"],
                f"El modelo agotó su presupuesto de respuesta; se reintenta con {nuevo} tokens "
                f"en lugar de {anterior}.",
                json.dumps({"task_id": task_id, "previous_tokens": anterior, "tokens": nuevo}),
            ),
        )
        return True

    # ---------------------------------------------------------------- escribir

    @staticmethod
    def _escribir_tarea(
        connection: sqlite3.Connection,
        task_id: str,
        payload: dict[str, Any],
        target: TaskStatus,
        broker_result: dict[str, Any] | None,
        error: dict[str, Any],
    ) -> None:
        result = resultado_de(broker_result) if target is TaskStatus.SUCCESS else None
        progress = dict(payload.get("progress") or {})
        progress.setdefault("phase", payload["status"])
        terminal = target in {TaskStatus.SUCCESS, TaskStatus.ERROR, TaskStatus.CANCELLED}
        connection.execute(
            "UPDATE tasks SET status = ?, response_json = ?, result_json = ?, error_code = ?, "
            "error_message = ?, error_retryable = ?, model_used = ?, started_at = COALESCE(?, started_at), "
            "completed_at = ?, progress_json = ?, broker_metadata_json = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE task_id = ?",
            (
                target.value,
                json.dumps(payload, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                error.get("code"),
                error.get("message"),
                int(error["retryable"]) if "retryable" in error else None,
                modelo_usado(broker_result),
                payload.get("created_at") if target is TaskStatus.PROCESSING else None,
                payload.get("updated_at") if terminal else None,
                json.dumps(progress, ensure_ascii=False),
                json.dumps(metadata_de(broker_result), ensure_ascii=False),
                task_id,
            ),
        )

    @staticmethod
    def _marcar_captura_en_proceso(connection: sqlite3.Connection, capture_id: str) -> None:
        connection.execute(
            "UPDATE captures SET status = 'PROCESSING', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
            "WHERE capture_id = ? AND status IN ('SUBMITTING', 'QUEUED')",
            (capture_id,),
        )

    # ------------------------------------------------------------------ cierre

    def _cerrar_paso_con_exito(
        self,
        connection: sqlite3.Connection,
        current: sqlite3.Row,
        task_id: str,
        broker_result: dict[str, Any] | None,
    ) -> None:
        self._registrar_avisos(connection, current["capture_id"], task_id, broker_result)
        connection.execute(
            "UPDATE workflows SET completed_steps = completed_steps + 1, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE workflow_id = ?",
            (current["workflow_id"],),
        )

    @staticmethod
    def _registrar_avisos(
        connection: sqlite3.Connection,
        capture_id: str,
        task_id: str,
        broker_result: dict[str, Any] | None,
    ) -> None:
        """Deja constancia de los avisos del Broker y de las citas sin respaldo.

        Un resultado con avisos sigue siendo un resultado, pero quien lo revise
        tiene derecho a saber con qué reservas llegó.
        """
        resultado = broker_result or {}
        warning_count = len(resultado.get("warnings", []))
        if warning_count:
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) "
                "VALUES (?, 'BROKER_RESULT_WARNING', ?, ?)",
                (
                    capture_id,
                    f"El Broker informó {warning_count} aviso(s); consulte el detalle de la tarea.",
                    json.dumps({"task_id": task_id, "warning_count": warning_count}, ensure_ascii=False),
                ),
            )
        unsupported = ((resultado.get("agent") or {}).get("citations") or {}).get("unsupported", [])
        if unsupported:
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) "
                "VALUES (?, 'BROKER_CITATION_WARNING', ?, ?)",
                (
                    capture_id,
                    f"El Broker detectó {len(unsupported)} enlace(s) citado(s) "
                    "sin respaldo en las fuentes consultadas.",
                    json.dumps({"task_id": task_id, "unsupported_count": len(unsupported)}, ensure_ascii=False),
                ),
            )

    def _cerrar_paso_con_fallo(
        self,
        connection: sqlite3.Connection,
        current: sqlite3.Row,
        task_id: str,
        target: TaskStatus,
        error: dict[str, Any],
    ) -> None:
        """Falla el workflow, salvo que el consenso pueda caer a `single`."""
        may_fallback = (
            target is TaskStatus.ERROR
            and current["execution_strategy"] == "mixture_of_agents"
            and bool(current["strategy_fallback_allowed"])
            and error.get("code") in self.CONSENSUS_FALLBACK_CODES
        )
        if may_fallback:
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) "
                "VALUES (?, 'CONSENSUS_FALLBACK_REQUIRED', ?, ?)",
                (
                    current["capture_id"],
                    "La tarea necesita la alternativa de ejecución configurada.",
                    # Only the allowlisted fallback code belongs in the activity log.
                    json.dumps({"task_id": task_id, "error_code": error["code"]}),
                ),
            )
            return
        self._fail_workflow(
            connection,
            current["workflow_id"],
            current["capture_id"],
            error.get("code", target.value),
            error.get("message", target.value),
        )

    def finish_workflow(self, workflow_id: str, final_result: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            workflow = connection.execute(
                "SELECT capture_id FROM workflows WHERE workflow_id = ?", (workflow_id,)
            ).fetchone()
            if workflow is None:
                raise ValueError("Workflow inexistente")
            connection.execute(
                "UPDATE workflows SET status = 'SUCCESS', final_result = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE workflow_id = ? AND status IN ('PLANNED', 'RUNNING')",
                (final_result, workflow_id),
            )
            connection.execute(
                "UPDATE captures SET status = 'PROCESSING', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE capture_id = ? AND status IN ('SUBMITTING', 'QUEUED', 'PROCESSING')",
                (workflow["capture_id"],),
            )
