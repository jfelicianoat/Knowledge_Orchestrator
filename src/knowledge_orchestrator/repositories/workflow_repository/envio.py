"""Envío al Broker: tomar la tarea, aceptarla, soltarla o darla por fallida.

`claim_submission` es la pieza que impide el envío doble tras un reinicio:
quien no consigue marcar la tarea como suya, no la manda.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from knowledge_orchestrator.domain.broker_models import (
    BrokerTaskRecord,
)
from knowledge_orchestrator.repositories.workflow_repository.consulta import ConsultaMixin
from knowledge_orchestrator.repositories.workflow_repository.filas import _task


def request_cost(request_json: str) -> float | None:
    """Lo que una petición puede gastar como máximo (`None` = sin límite)."""

    try:
        value = (json.loads(request_json).get("model_requirements") or {}).get("max_cost_usd")
    except (json.JSONDecodeError, AttributeError):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, float(value))


def release_reservation(connection: sqlite3.Connection, task_id: str, *, actual_cost: float | None) -> None:
    """Liquida lo reservado por una tarea contra lo que costó de verdad.

    Sin coste informado y con la tarea ya ejecutada se conserva la reserva
    entera: es la lectura prudente. Lo que sobra vuelve a la bolsa.
    """

    row = connection.execute(
        "SELECT workflow_id, budget_reserved_usd FROM tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    if row is None or actual_cost is None:
        return
    reserved = float(row["budget_reserved_usd"] or 0.0)
    kept = min(reserved, max(0.0, float(actual_cost)))
    refund = reserved - kept
    if refund <= 0:
        return
    connection.execute("UPDATE tasks SET budget_reserved_usd = ? WHERE task_id = ?", (kept, task_id))
    connection.execute(
        "UPDATE workflows SET budget_reserved_usd = MAX(0, budget_reserved_usd - ?) WHERE workflow_id = ?",
        (refund, row["workflow_id"]),
    )


class EnvioMixin(ConsultaMixin):
    """Ciclo de vida del envío de una tarea al Broker."""

    def claim_submission(self, task_id: str) -> BrokerTaskRecord | None:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT t.task_id, t.workflow_id, t.capture_id, t.request_json, w.status AS workflow_status, "
                "w.budget_usd, w.budget_reserved_usd FROM tasks t JOIN workflows w ON w.workflow_id = t.workflow_id "
                "WHERE t.task_id = ? AND t.status = 'READY'",
                (task_id,),
            ).fetchone()
            if row is None or row["workflow_status"] not in {"PLANNED", "RUNNING"}:
                return None
            cost = request_cost(row["request_json"])
            if row["budget_usd"] is not None and cost is not None:
                # La bolsa es del documento: fragmentos, síntesis, reducciones y
                # reintentos reservan de ella antes de salir (auditoría H08).
                if float(row["budget_reserved_usd"]) + cost > float(row["budget_usd"]) + 1e-9:
                    message = (
                        f"El documento agotó su presupuesto de {float(row['budget_usd']):.4f} USD "
                        f"(reservado {float(row['budget_reserved_usd']):.4f}); esta petición pedía {cost:.4f}."
                    )
                    connection.execute(
                        "UPDATE tasks SET status = 'ERROR', error_code = 'DOCUMENT_BUDGET_EXHAUSTED', "
                        "error_message = ?, error_retryable = 0, "
                        "completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
                        "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE task_id = ?",
                        (message, task_id),
                    )
                    self._fail_workflow(
                        connection, row["workflow_id"], row["capture_id"], "DOCUMENT_BUDGET_EXHAUSTED", message,
                    )
                    return None
            cursor = connection.execute(
                "UPDATE tasks SET status = 'SUBMITTING', attempt = attempt + 1, "
                "budget_reserved_usd = budget_reserved_usd + ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE task_id = ? AND status = 'READY'",
                (cost or 0.0, task_id),
            )
            if cursor.rowcount != 1:
                return None
            connection.execute(
                "UPDATE workflows SET budget_reserved_usd = budget_reserved_usd + ? WHERE workflow_id = ?",
                (cost or 0.0, row["workflow_id"]),
            )
            return _task(connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone())

    def mark_accepted(self, task_id: str, response: dict[str, Any]) -> None:
        with self.database.transaction(immediate=True) as connection:
            task = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if task is not None and task["status"] == "CANCEL_REQUESTED":
                # Se canceló el documento mientras el POST estaba en vuelo: se
                # guardan los identificadores para poder cancelarla en el Broker.
                connection.execute(
                    "UPDATE tasks SET status_url = ?, cancel_url = ?, response_json = ?, broker_task_id = ?, "
                    "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE task_id = ?",
                    (response["status_url"], response["cancel_url"], json.dumps(response), response["task_id"],
                     task_id),
                )
                return
            if task is None or task["status"] != "SUBMITTING":
                raise RuntimeError("La tarea no está SUBMITTING")
            connection.execute(
                "UPDATE tasks SET status = 'QUEUED', status_url = ?, cancel_url = ?, response_json = ?, "
                "broker_task_id = ?, execution_strategy = ?, execution_preset = ?, selection_mode = ?, "
                "queued_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), next_retry_at = NULL, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE task_id = ?",
                (response["status_url"], response["cancel_url"], json.dumps(response), response["task_id"],
                 response["execution_strategy"], response["execution_preset"], response["selection_mode"], task_id),
            )
            connection.execute(
                "UPDATE workflows SET status = 'RUNNING', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE workflow_id = ? AND status = 'PLANNED'",
                (task["workflow_id"],),
            )
            connection.execute(
                "UPDATE captures SET status = 'QUEUED', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE capture_id = ? AND status = 'SUBMITTING'",
                (task["capture_id"],),
            )

    def release_submission(self, task_id: str, *, next_retry_at: str, message: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            # No llegó al Broker: lo reservado vuelve a la bolsa del documento.
            release_reservation(connection, task_id, actual_cost=0.0)
            connection.execute(
                "UPDATE tasks SET status = 'READY', next_retry_at = ?, error_code = 'TRANSIENT_SUBMISSION', "
                "error_message = ?, error_retryable = 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE task_id = ? AND status = 'SUBMITTING'",
                (next_retry_at, message, task_id),
            )

    def mark_submission_error(self, task_id: str, code: str, message: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            task = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if task is None:
                return
            release_reservation(connection, task_id, actual_cost=0.0)
            connection.execute(
                "UPDATE tasks SET status = 'ERROR', error_code = ?, error_message = ?, error_retryable = 0, "
                "completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE task_id = ?",
                (code, message, task_id),
            )
            self._fail_workflow(connection, task["workflow_id"], task["capture_id"], code, message)
