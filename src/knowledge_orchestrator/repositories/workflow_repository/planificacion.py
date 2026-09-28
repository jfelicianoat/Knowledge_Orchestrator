"""Alta de workflows y tareas, y recuperación de lo que quedó a medias.

Es la parte que decide qué hay que hacer y lo deja escrito antes de que
nadie lo intente: un reinicio a mitad de envío no puede duplicar tareas ni
perder las que ya estaban planificadas.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from typing import Any

from knowledge_orchestrator.domain.broker_contracts import validate_create_task_request
from knowledge_orchestrator.domain.broker_models import (
    PlannedTask,
    TaskStatus,
    WorkflowRecord,
)
from knowledge_orchestrator.repositories.workflow_repository.base import RepositorioBase
from knowledge_orchestrator.repositories.workflow_repository.filas import _workflow


class PlanificacionMixin(RepositorioBase):
    """Planificación de trabajo y recuperación de envíos interrumpidos."""

    def list_unplanned_capture_ids(self) -> list[str]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                # Sin workflow vivo ni resultado vigente. Un workflow fallido o
                # cancelado, o un borrador descartado, no impiden volver a
                # planificar cuando la persona lo pide (la captura vuelve a PENDING).
                "SELECT c.capture_id FROM captures c "
                "WHERE c.status = 'PENDING' AND c.domain_enriched_at IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM workflows w WHERE w.capture_id = c.capture_id "
                "AND (w.status IN ('PLANNED', 'RUNNING') "
                "OR (w.status = 'SUCCESS' AND COALESCE(w.review_status, '') <> 'REJECTED'))) "
                "ORDER BY c.created_at, c.capture_id"
            ).fetchall()
            return [row["capture_id"] for row in rows]

    def fail_unplannable_capture(self, capture_id: str, code: str, message: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute(
                "UPDATE captures SET status = 'FAILED', last_error_code = ?, last_error_message = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE capture_id = ? AND status = 'PENDING'",
                (code, message, capture_id),
            )
            if changed.rowcount:
                connection.execute(
                    "INSERT INTO events(capture_id, event_type, message, details_json) VALUES (?, ?, ?, '{}')",
                    (capture_id, code, message),
                )

    def reopen_failed_capture(self, capture_id: str) -> bool:
        """Devuelve a la cola local una captura que falló antes de tener workflow."""

        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute(
                "UPDATE captures SET status = 'PENDING', last_error_code = NULL, last_error_message = NULL, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE capture_id = ? AND status = 'FAILED' "
                "AND domain_enriched_at IS NOT NULL AND processing_path IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM workflows w WHERE w.capture_id = captures.capture_id "
                "AND w.status IN ('PLANNED', 'RUNNING', 'SUCCESS'))",
                (capture_id,),
            )
            if changed.rowcount:
                connection.execute(
                    "INSERT INTO events(capture_id, event_type, message, details_json) "
                    "VALUES (?, 'MANUAL_RETRY_REQUESTED', 'Se vuelve a planificar el documento', '{}')",
                    (capture_id,),
                )
            return changed.rowcount == 1

    def next_revision(self, capture_id: str) -> int:
        with closing(self.database.connect()) as connection:
            return int(connection.execute(
                "SELECT COALESCE(MAX(revision), 0) + 1 FROM workflows WHERE capture_id = ?", (capture_id,)
            ).fetchone()[0])

    def list_resumable_workflow_ids(self) -> list[str]:
        with closing(self.database.connect()) as connection:
            return [row["workflow_id"] for row in connection.execute(
                "SELECT workflow_id FROM workflows WHERE status IN ('PLANNED', 'RUNNING') "
                "ORDER BY created_at, workflow_id"
            ).fetchall()]

    def recover_interrupted_submissions(self) -> int:
        """Reabre envíos interrumpidos; la clave idempotente evita duplicarlos en el Broker."""
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status = 'READY', next_retry_at = NULL, "
                "error_code = 'INTERRUPTED_SUBMISSION', "
                "error_message = 'Reenvío idempotente tras reinicio', error_retryable = 1, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE status = 'SUBMITTING'"
            )
            return cursor.rowcount

    def upgrade_legacy_ready_requests(self) -> int:
        """Convierte tareas locales nunca finalizadas del contrato Broker v1 al v2."""
        upgraded = 0
        with self.database.transaction(immediate=True) as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE broker_contract_version = '1.0' AND status IN ('READY', 'SUBMITTING')"
            ).fetchall()
            for row in rows:
                try:
                    legacy = json.loads(row["request_json"])
                    inference = legacy["inference"]
                    if inference.get("kind") != "chat":
                        raise ValueError("solo se migra chat")
                    messages = inference["messages"]
                    system = "\n\n".join(item["content"] for item in messages if item.get("role") == "system")
                    conversation = "\n\n".join(
                        f"[{item.get('role', 'user')}]\n{item['content']}"
                        for item in messages if item.get("role") != "system"
                    )
                    routing = legacy["routing"]
                    context = legacy["client_context"]
                    payload = {
                        "idempotency_key": legacy["idempotency_key"],
                        "request_id": legacy["task_id"],
                        "content": {
                            "prompt": f"<system_instructions>\n{system}\n</system_instructions>\n\n"
                                      f"<user_request>\n{conversation}\n</user_request>",
                            "attachments": [],
                            "metadata": {
                                "workflow_id": context["workflow_id"],
                                "step_id": context["step_id"],
                            },
                        },
                        "output": {"format": "markdown", "json_schema": None, "language": "es"},
                        "generation": {
                            "temperature": inference["temperature"],
                            "max_output_tokens": inference["max_output_tokens"],
                        },
                        "model_requirements": {
                            "preferred_model": routing["preferred_model"],
                            "fallback_allowed": routing["fallback_allowed"],
                            "cloud_allowed": False,
                            "allowed_providers": ["ollama"],
                            "max_cost_usd": routing.get("max_cost_usd"),
                        },
                        "execution": {
                            "strategy": "single", "preset": "fast", "scheduling": "adaptive",
                            "max_proposers": 1, "max_judges": 0, "max_rounds": 1,
                            "timeout_seconds": 600, "early_stop": True,
                            "selection": {
                                "mode": "auto", "diversity_policy": "different_families",
                                "arbiter_policy": "strongest_available",
                                "allow_substitution": routing["fallback_allowed"],
                                "proposers": [], "required_proposers": [], "proposer_count": 1,
                            },
                        },
                        "risk": {"data_classification": "local_only", "human_review_required": False},
                        "priority": 100,
                    }
                    validate_create_task_request(payload)
                except (KeyError, TypeError, ValueError) as error:
                    connection.execute(
                        "UPDATE tasks SET status = 'ERROR', error_code = 'CONTRACT_MIGRATION_FAILED', "
                        "error_message = ?, error_retryable = 0 WHERE task_id = ?",
                        (str(error), row["task_id"]),
                    )
                    self._fail_workflow(
                        connection, row["workflow_id"], row["capture_id"],
                        "CONTRACT_MIGRATION_FAILED", str(error),
                    )
                    continue
                encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                connection.execute(
                    "UPDATE tasks SET request_json = ?, request_hash = ?, broker_contract_version = '2.0', "
                    "status = 'READY', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE task_id = ?",
                    (encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest(), row["task_id"]),
                )
                upgraded += 1
        return upgraded

    def create_workflow(
        self,
        *,
        workflow_id: str,
        capture_id: str,
        revision: int,
        profile_id: int,
        profile_revision: int,
        strategy: str,
        total_steps: int,
        plan: dict[str, Any],
        tasks: Iterable[PlannedTask],
        review_required: bool = False,
        budget_usd: float | None = None,
    ) -> WorkflowRecord:
        task_list = list(tasks)
        with self.database.transaction(immediate=True) as connection:
            existing = connection.execute(
                "SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,)
            ).fetchone()
            if existing:
                return _workflow(existing)
            cursor = connection.execute(
                "UPDATE captures SET status = 'SUBMITTING', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE capture_id = ? AND status = 'PENDING' AND domain_enriched_at IS NOT NULL",
                (capture_id,),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("La captura no está preparada para crear un workflow")
            connection.execute(
                "INSERT INTO workflows (workflow_id, capture_id, revision, profile_id, profile_revision, "
                "status, strategy, total_steps, plan_json, review_required, budget_usd) "
                "VALUES (?, ?, ?, ?, ?, 'PLANNED', ?, ?, ?, ?, ?)",
                (
                    workflow_id,
                    capture_id,
                    revision,
                    profile_id,
                    profile_revision,
                    strategy,
                    total_steps,
                    json.dumps(plan, ensure_ascii=False, sort_keys=True),
                    int(review_required),
                    budget_usd,
                ),
            )
            for task in task_list:
                self._insert_task(connection, task, TaskStatus.READY)
            row = connection.execute("SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,)).fetchone()
            return _workflow(row)

    def record_workflow_event(
        self, workflow_id: str, event_type: str, message: str, details: dict[str, Any] | None = None,
    ) -> None:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT capture_id FROM workflows WHERE workflow_id = ?", (workflow_id,)
            ).fetchone()
            if row is None:
                return
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) VALUES (?, ?, ?, ?)",
                (row["capture_id"], event_type, message,
                 json.dumps({"workflow_id": workflow_id, **(details or {})}, ensure_ascii=False)),
            )

    def insert_synthesis_task(self, task: PlannedTask, dependency_ids: list[str]) -> None:
        with self.database.transaction(immediate=True) as connection:
            if connection.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task.task_id,)).fetchone():
                return
            self._insert_task(connection, task, TaskStatus.READY)
            connection.executemany(
                "INSERT INTO task_dependencies(task_id, depends_on_task_id) VALUES (?, ?)",
                [(task.task_id, dependency_id) for dependency_id in dependency_ids],
            )

    @staticmethod
    def _insert_task(connection: sqlite3.Connection, task: PlannedTask, status: TaskStatus) -> None:
        encoded = json.dumps(dict(task.request), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        connection.execute(
            "INSERT INTO tasks (task_id, capture_id, workflow_id, step_id, status, request_json, "
            "step_kind, sequence_index, idempotency_key, request_hash, input_text, broker_contract_version, "
            "strategy_fallback_allowed, replacement_for_task_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '2.0', ?, ?)",
            (
                task.task_id,
                task.capture_id,
                task.workflow_id,
                task.step_id,
                status.value,
                encoded,
                task.step_kind.value,
                task.sequence_index,
                task.idempotency_key,
                hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                task.input_text,
                int(task.strategy_fallback_allowed),
                task.replacement_for_task_id,
            ),
        )
