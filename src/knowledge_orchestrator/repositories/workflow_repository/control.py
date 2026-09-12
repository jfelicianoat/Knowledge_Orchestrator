"""Órdenes del operador: cancelar, reintentar e ignorar.

Son las tres cosas que un humano puede pedirle al sistema desde el panel, y
las tres tienen que dejar la base en un estado del que se pueda seguir.
"""
from __future__ import annotations

import hashlib
import json

from knowledge_orchestrator.repositories.workflow_repository.envio import EnvioMixin


class ControlMixin(EnvioMixin):
    """Cancelación, reintento y descarte de capturas fallidas."""

    def request_cancel(self, task_id: str) -> bool:
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status = 'CANCEL_REQUESTED', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE task_id = ? AND status IN ('QUEUED', 'PROCESSING')",
                (task_id,),
            )
            return cursor.rowcount == 1

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
            # modelo en Ajustes no servía de nada (reproducido con un modelo que
            # agotaba su presupuesto razonando). El prompt no se toca.
            policy = connection.execute(
                "SELECT p.preferred_model, p.temperature, p.max_output_tokens FROM workflows w "
                "JOIN profiles p ON p.profile_id = w.profile_id WHERE w.workflow_id = ?",
                (task["workflow_id"],),
            ).fetchone()
            if policy is not None and isinstance(request.get("generation"), dict):
                request.setdefault("model_requirements", {})["preferred_model"] = (
                    policy["preferred_model"] or None
                )
                request["generation"]["temperature"] = float(policy["temperature"])
                request["generation"]["max_output_tokens"] = int(policy["max_output_tokens"])
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
                "VALUES (?, 'MANUAL_RETRY_REQUESTED', 'Reintento manual solicitado', ?)",
                (task["capture_id"], json.dumps({"task_id": task_id, "attempt": retry_number})),
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
