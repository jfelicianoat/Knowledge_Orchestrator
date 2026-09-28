"""Órdenes del operador: cancelar, reintentar e ignorar.

Son las tres cosas que un humano puede pedirle al sistema desde el panel, y
las tres tienen que dejar la base en un estado del que se pueda seguir.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from typing import Any

from knowledge_orchestrator.repositories.domain_repository import DomainRepository
from knowledge_orchestrator.repositories.workflow_repository.envio import EnvioMixin

#: Campos de la petición que son política y no contenido: se rehacen enteros.
POLICY_FIELDS = ("model_requirements", "generation", "execution", "risk", "prompt_compression",
                 "auxiliary_invocations")


def refreshed_policy(
    connection: sqlite3.Connection, task: sqlite3.Row, request: dict[str, Any],
) -> dict[str, Any] | None:
    """Sustituye en `request` toda la política por la del perfil vigente.

    Devuelve un resumen legible de la política efectiva, o `None` si el perfil
    ya no existe (entonces se reintenta la petición original tal cual).
    """

    from knowledge_orchestrator.services.prompting import build_chat_request

    workflow = connection.execute(
        "SELECT profile_id, plan_json FROM workflows WHERE workflow_id = ?", (task["workflow_id"],)
    ).fetchone()
    if workflow is None:
        return None
    profile = DomainRepository.profile_from_connection(connection, int(workflow["profile_id"]))
    if profile is None:
        return None
    try:
        plan = json.loads(workflow["plan_json"] or "{}")
    except json.JSONDecodeError:
        plan = {}
    window = int(plan.get("max_context_tokens") or 16_000)
    output_tokens = min(profile.max_output_tokens, max(1_000, (window - 1_000) // 2))
    share = (request.get("model_requirements") or {}).get("max_cost_usd", profile.max_cost_usd)
    effective = replace(profile, max_output_tokens=output_tokens, max_cost_usd=share)
    fresh = build_chat_request(
        task_id=str(request.get("request_id") or task["task_id"]),
        idempotency_key=str(task["idempotency_key"]),
        workflow_id=str(task["workflow_id"]),
        step_id=str(task["step_id"]),
        profile=effective,
        system_content="-",
        user_content="-",
        execution_step=str(task["step_kind"]).lower(),
    )
    for field in POLICY_FIELDS:
        if field in fresh:
            request[field] = fresh[field]
        else:
            request.pop(field, None)
    requirements = fresh["model_requirements"]
    return {
        "profile_revision": profile.revision,
        "model": requirements.get("preferred_model") or "automático",
        "data_classification": profile.data_classification,
        "fallback_allowed": bool(requirements.get("fallback_allowed")),
        "max_output_tokens": output_tokens,
        "summary": (
            f"modelo {requirements.get('preferred_model') or 'automático'}, "
            f"privacidad {profile.data_classification}, "
            f"sustituciones {'permitidas' if requirements.get('fallback_allowed') else 'prohibidas'}"
        ),
    }


class ControlMixin(EnvioMixin):
    """Cancelación, reintento y descarte de capturas fallidas."""

    def request_cancel(self, task_id: str) -> bool:
        """Cancela el documento al que pertenece la tarea, no solo esa tarea.

        Quien pulsa «Cancelar» quiere parar el documento. Cancelar una tarea
        suelta dejaba las demás listas para salir (reproducido: 10 de 11
        fragmentos seguían despachables) y el documento acababa en ERROR.
        """

        with closing(self.database.connect()) as connection:
            row = connection.execute("SELECT workflow_id FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return bool(row) and self.cancel_workflow(str(row["workflow_id"]))

    def cancel_capture(self, capture_id: str) -> bool:
        """Cancela el workflow vivo de una captura (el documento que ve la persona).

        Si aún no se ha planificado (espera en la cola local), se cancela la
        captura directamente para que el planificador no llegue a tomarla.
        """

        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT workflow_id FROM workflows WHERE capture_id = ? AND status IN ('PLANNED', 'RUNNING') "
                "ORDER BY revision DESC LIMIT 1",
                (capture_id,),
            ).fetchone()
        if row is not None:
            return self.cancel_workflow(str(row["workflow_id"]))
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute(
                "UPDATE captures SET status = 'CANCELLED', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE capture_id = ? AND status = 'PENDING' AND NOT EXISTS (SELECT 1 FROM workflows w "
                "WHERE w.capture_id = captures.capture_id AND w.status IN ('PLANNED', 'RUNNING'))",
                (capture_id,),
            ).rowcount
            if changed:
                connection.execute(
                    "INSERT INTO events(capture_id, event_type, message, details_json) "
                    "VALUES (?, 'CAPTURE_CANCELLED', 'Cancelado antes de procesarse; el original se conserva.', "
                    "'{}')",
                    (capture_id,),
                )
            return changed == 1

    def cancel_workflow(self, workflow_id: str) -> bool:
        """Para un documento entero de forma durable (auditoría H02).

        - Lo que no ha salido (READY) se cancela aquí mismo.
        - Lo que está en el Broker o en vuelo pasa a CANCEL_REQUESTED y el
          worker pide su cancelación remota.
        - El workflow y la captura quedan CANCELLED, distinto de ERROR: no es
          una incidencia. Desde ese momento no se despacha ni se sintetiza nada
          más, y lo que llegue tarde del Broker no lo reabre.

        Si el documento ya terminó (la finalización ganó la carrera), no hace
        nada y devuelve `False`.
        """

        with self.database.transaction(immediate=True) as connection:
            workflow = connection.execute(
                "SELECT capture_id FROM workflows WHERE workflow_id = ? AND status IN ('PLANNED', 'RUNNING')",
                (workflow_id,),
            ).fetchone()
            if workflow is None:
                return False
            local = connection.execute(
                "UPDATE tasks SET status = 'CANCELLED', completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE workflow_id = ? AND status = 'READY'",
                (workflow_id,),
            ).rowcount
            remote = connection.execute(
                "UPDATE tasks SET status = 'CANCEL_REQUESTED', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE workflow_id = ? AND status IN ('SUBMITTING', 'QUEUED', 'PROCESSING')",
                (workflow_id,),
            ).rowcount
            connection.execute(
                "UPDATE workflows SET status = 'CANCELLED', error_code = NULL, error_message = NULL, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE workflow_id = ?",
                (workflow_id,),
            )
            connection.execute(
                "UPDATE captures SET status = 'CANCELLED', last_error_code = NULL, last_error_message = NULL, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE capture_id = ? "
                "AND status IN ('PENDING', 'SUBMITTING', 'QUEUED', 'PROCESSING')",
                (workflow["capture_id"],),
            )
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) "
                "VALUES (?, 'CAPTURE_CANCELLED', ?, ?)",
                (
                    workflow["capture_id"],
                    "Procesamiento cancelado por el usuario; el original se conserva.",
                    json.dumps({"workflow_id": workflow_id, "local_tasks": local, "remote_tasks": remote}),
                ),
            )
            return True

    def settle_orphan_cancellations(self) -> int:
        """Cierra cancelaciones que nunca llegaron al Broker.

        Una tarea cancelada mientras su envío estaba en vuelo queda en
        CANCEL_REQUESTED; si el envío no llegó a aceptarse, no hay nada que
        cancelar fuera y se cierra aquí. Solo la llama el worker entre ciclos,
        cuando no hay ningún envío suyo en curso.
        """

        with self.database.transaction(immediate=True) as connection:
            return connection.execute(
                "UPDATE tasks SET status = 'CANCELLED', completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE status = 'CANCEL_REQUESTED' AND broker_task_id IS NULL",
            ).rowcount

    def retry_failed_task(self, task_id: str) -> bool:
        """Reabre una tarea fallida con una clave idempotente nueva."""
        with self.database.transaction(immediate=True) as connection:
            task = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ? AND status = 'ERROR'", (task_id,)
            ).fetchone()
            if task is None:
                return False
            request = json.loads(task["request_json"])
            # Reintentar es «vuelve a intentarlo con lo que hay ahora». La
            # petición se congela al planificar, así que sin esto se reenviaba
            # el modelo y la longitud con los que ya había fallado: cambiar el
            # modelo en Ajustes no servía de nada. Pero refrescar solo el modelo
            # y la temperatura producía una petición híbrida —modelo nuevo con
            # privacidad y sustituciones viejas— (auditoría H12). Ahora se
            # rehace la política ENTERA con el perfil vigente; el prompt y la
            # parte del presupuesto del documento asignada a esta tarea no cambian.
            policy = refreshed_policy(connection, task, request)
            retry_number = int(task["attempt"] or 0) + 1
            base_key = str(task["idempotency_key"]).split(":manual-", 1)[0]
            idempotency_key = f"{base_key}:manual-{retry_number}"
            request["idempotency_key"] = idempotency_key
            encoded = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            connection.execute(
                "UPDATE tasks SET status = 'READY', request_json = ?, request_hash = ?, "
                "idempotency_key = ?, response_json = NULL, result_json = NULL, status_url = NULL, "
                "cancel_url = NULL, broker_task_id = NULL, error_code = NULL, error_message = NULL, "
                "error_retryable = NULL, next_retry_at = NULL, model_used = NULL, queued_at = NULL, "
                "started_at = NULL, completed_at = NULL, progress_json = '{}', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE task_id = ?",
                (encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest(), idempotency_key, task_id),
            )
            connection.execute(
                "UPDATE workflows SET status = 'RUNNING', error_code = NULL, error_message = NULL, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE workflow_id = ?",
                (task["workflow_id"],),
            )
            connection.execute(
                "UPDATE captures SET status = 'PENDING', last_error_code = NULL, last_error_message = NULL, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE capture_id = ?",
                (task["capture_id"],),
            )
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) "
                "VALUES (?, 'MANUAL_RETRY_REQUESTED', ?, ?)",
                (
                    task["capture_id"],
                    "Reintento manual con la configuración actual del perfil"
                    + (f": {policy['summary']}" if policy else ""),
                    json.dumps({"task_id": task_id, "attempt": retry_number,
                                "policy": policy or {}}, ensure_ascii=False),
                ),
            )
            return True

    def ignore_failed_capture(self, capture_id: str) -> bool:
        """Cierra una incidencia fallida sin borrar su historial."""
        with self.database.transaction(immediate=True) as connection:
            capture = connection.execute(
                "SELECT status FROM captures WHERE capture_id = ? AND status = 'FAILED'", (capture_id,)
            ).fetchone()
            if capture is None:
                return False
            connection.execute(
                "UPDATE tasks SET status = 'CANCELLED', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE capture_id = ? AND status = 'ERROR'",
                (capture_id,),
            )
            connection.execute(
                "UPDATE workflows SET status = 'CANCELLED', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE capture_id = ? AND status = 'ERROR'",
                (capture_id,),
            )
            connection.execute(
                "UPDATE captures SET status = 'CANCELLED', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE capture_id = ?",
                (capture_id,),
            )
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) "
                "VALUES (?, 'CAPTURE_IGNORED', 'Incidencia ignorada por el usuario', '{}')",
                (capture_id,),
            )
            return True
