"""Envío al Broker: tomar la tarea, aceptarla, soltarla o darla por fallida.

`claim_submission` es la pieza que impide el envío doble tras un reinicio:
quien no consigue marcar la tarea como suya, no la manda.
"""
from __future__ import annotations

import json
from typing import Any

from knowledge_orchestrator.domain.broker_models import (
    BrokerTaskRecord,
)
from knowledge_orchestrator.repositories.workflow_repository.consulta import ConsultaMixin
from knowledge_orchestrator.repositories.workflow_repository.filas import _task


class EnvioMixin(ConsultaMixin):
    """Ciclo de vida del envío de una tarea al Broker."""

    def claim_submission(self, task_id: str) -> BrokerTaskRecord | None:
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status = 'SUBMITTING', attempt = attempt + 1, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE task_id = ? AND status = 'READY'",
                (task_id,),
            )
            if cursor.rowcount != 1:
                return None
            return _task(connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone())

    def mark_accepted(self, task_id: str, response: dict[str, Any]) -> None:
        with self.database.transaction(immediate=True) as connection:
            task = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
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
            connection.execute(
                "UPDATE tasks SET status = 'ERROR', error_code = ?, error_message = ?, error_retryable = 0, "
                "completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE task_id = ?",
                (code, message, task_id),
            )
            self._fail_workflow(connection, task["workflow_id"], task["capture_id"], code, message)
