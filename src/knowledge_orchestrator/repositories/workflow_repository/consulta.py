"""Lecturas: qué workflows y tareas hay, y cuáles se pueden despachar."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

from knowledge_orchestrator.domain.broker_models import (
    BrokerTaskRecord,
    WorkflowRecord,
)
from knowledge_orchestrator.repositories.workflow_repository.filas import _task, _workflow
from knowledge_orchestrator.repositories.workflow_repository.planificacion import PlanificacionMixin


class ConsultaMixin(PlanificacionMixin):
    """Consultas sin efectos: nada de lo que hay aquí escribe."""

    def get_workflow(self, workflow_id: str) -> WorkflowRecord | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute("SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,)).fetchone()
            return _workflow(row) if row else None

    def get_task(self, task_id: str) -> BrokerTaskRecord | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            return _task(row) if row else None

    def list_workflow_tasks(self, workflow_id: str) -> list[BrokerTaskRecord]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE workflow_id = ? ORDER BY sequence_index, task_id", (workflow_id,)
            ).fetchall()
            return [_task(row) for row in rows]

    def list_dispatchable(self, *, limit: int = 100) -> list[BrokerTaskRecord]:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT t.* FROM tasks t WHERE t.status = 'READY' AND t.broker_contract_version = '2.0' "
                "AND (t.next_retry_at IS NULL OR t.next_retry_at <= ?) "
                "AND NOT EXISTS (SELECT 1 FROM task_dependencies d JOIN tasks parent "
                "ON parent.task_id = d.depends_on_task_id WHERE d.task_id = t.task_id "
                "AND parent.status <> 'SUCCESS') ORDER BY t.created_at, t.sequence_index LIMIT ?",
                (now, limit),
            ).fetchall()
            return [_task(row) for row in rows]

    def list_active_tasks(self) -> list[BrokerTaskRecord]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE status IN ('QUEUED', 'PROCESSING', 'CANCEL_REQUESTED') "
                "ORDER BY queued_at, created_at"
            ).fetchall()
            return [_task(row) for row in rows]

    def list_cancel_requested(self) -> list[BrokerTaskRecord]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE status = 'CANCEL_REQUESTED' ORDER BY updated_at"
            ).fetchall()
            return [_task(row) for row in rows]
