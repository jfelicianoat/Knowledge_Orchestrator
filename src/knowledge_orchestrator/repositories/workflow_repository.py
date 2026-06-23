from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Iterable

from knowledge_orchestrator.domain.broker_models import (
    BrokerTaskRecord,
    PlannedTask,
    StepKind,
    TaskStatus,
    WorkflowRecord,
    WorkflowStatus,
)

from .database import Database


def _task(row: sqlite3.Row) -> BrokerTaskRecord:
    return BrokerTaskRecord(
        task_id=row["task_id"],
        workflow_id=row["workflow_id"],
        capture_id=row["capture_id"],
        step_id=row["step_id"],
        step_kind=StepKind(row["step_kind"]),
        sequence_index=row["sequence_index"],
        status=TaskStatus(row["status"]),
        idempotency_key=row["idempotency_key"],
        request_json=row["request_json"],
        input_text=row["input_text"],
        attempt=row["attempt"],
        next_retry_at=row["next_retry_at"],
        status_url=row["status_url"],
        result_json=row["result_json"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        error_retryable=bool(row["error_retryable"]) if row["error_retryable"] is not None else None,
    )


def _workflow(row: sqlite3.Row) -> WorkflowRecord:
    return WorkflowRecord(
        workflow_id=row["workflow_id"],
        capture_id=row["capture_id"],
        revision=row["revision"],
        profile_id=row["profile_id"],
        profile_revision=row["profile_revision"],
        status=WorkflowStatus(row["status"]),
        strategy=row["strategy"],
        total_steps=row["total_steps"],
        completed_steps=row["completed_steps"],
        final_result=row["final_result"],
        error_code=row["error_code"],
        error_message=row["error_message"],
    )


class WorkflowRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_unplanned_capture_ids(self) -> list[str]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT c.capture_id FROM captures c LEFT JOIN workflows w ON w.capture_id = c.capture_id "
                "WHERE c.status = 'PENDING' AND c.domain_enriched_at IS NOT NULL AND w.workflow_id IS NULL "
                "ORDER BY c.created_at, c.capture_id"
            ).fetchall()
            return [row["capture_id"] for row in rows]

    def next_revision(self, capture_id: str) -> int:
        with closing(self.database.connect()) as connection:
            return int(connection.execute(
                "SELECT COALESCE(MAX(revision), 0) + 1 FROM workflows WHERE capture_id = ?", (capture_id,)
            ).fetchone()[0])

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
                "status, strategy, total_steps, plan_json) VALUES (?, ?, ?, ?, ?, 'PLANNED', ?, ?, ?)",
                (
                    workflow_id,
                    capture_id,
                    revision,
                    profile_id,
                    profile_revision,
                    strategy,
                    total_steps,
                    json.dumps(plan, ensure_ascii=False, sort_keys=True),
                ),
            )
            for task in task_list:
                self._insert_task(connection, task, TaskStatus.READY)
            row = connection.execute("SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,)).fetchone()
            return _workflow(row)

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
            "step_kind, sequence_index, idempotency_key, request_hash, input_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            ),
        )

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
                "SELECT t.* FROM tasks t WHERE t.status = 'READY' "
                "AND (t.next_retry_at IS NULL OR t.next_retry_at <= ?) "
                "AND NOT EXISTS (SELECT 1 FROM task_dependencies d JOIN tasks parent "
                "ON parent.task_id = d.depends_on_task_id WHERE d.task_id = t.task_id "
                "AND parent.status <> 'SUCCESS') ORDER BY t.created_at, t.sequence_index LIMIT ?",
                (now, limit),
            ).fetchall()
            return [_task(row) for row in rows]

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
                "queued_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), next_retry_at = NULL, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE task_id = ?",
                (response["status_url"], response["cancel_url"], json.dumps(response), task_id),
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

    def list_active_tasks(self) -> list[BrokerTaskRecord]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE status IN ('QUEUED', 'PROCESSING', 'CANCEL_REQUESTED') "
                "ORDER BY queued_at, created_at"
            ).fetchall()
            return [_task(row) for row in rows]

    def apply_status(self, task_id: str, payload: dict[str, Any]) -> bool:
        status_map = {
            "queued": TaskStatus.QUEUED,
            "processing": TaskStatus.PROCESSING,
            "success": TaskStatus.SUCCESS,
            "error": TaskStatus.ERROR,
            "cancel_requested": TaskStatus.CANCEL_REQUESTED,
            "cancelled": TaskStatus.CANCELLED,
        }
        target = status_map[payload["status"]]
        with self.database.transaction(immediate=True) as connection:
            current = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if current is None:
                raise ValueError("Tarea inexistente")
            if current["status"] in {"SUCCESS", "ERROR", "CANCELLED"}:
                return False
            result = payload.get("result")
            error = payload.get("error") or {}
            connection.execute(
                "UPDATE tasks SET status = ?, response_json = ?, result_json = ?, error_code = ?, "
                "error_message = ?, error_retryable = ?, model_used = ?, started_at = COALESCE(?, started_at), "
                "completed_at = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE task_id = ?",
                (
                    target.value,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    error.get("code"),
                    error.get("message"),
                    int(error["retryable"]) if "retryable" in error else None,
                    payload.get("model_used"),
                    payload.get("started_at"),
                    payload.get("completed_at") if target in {TaskStatus.SUCCESS, TaskStatus.ERROR, TaskStatus.CANCELLED} else None,
                    task_id,
                ),
            )
            if target is TaskStatus.PROCESSING:
                connection.execute(
                    "UPDATE captures SET status = 'PROCESSING', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                    "WHERE capture_id = ? AND status IN ('SUBMITTING', 'QUEUED')",
                    (current["capture_id"],),
                )
            if target is TaskStatus.SUCCESS:
                connection.execute(
                    "UPDATE workflows SET completed_steps = completed_steps + 1, "
                    "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE workflow_id = ?",
                    (current["workflow_id"],),
                )
            elif target in {TaskStatus.ERROR, TaskStatus.CANCELLED}:
                self._fail_workflow(
                    connection,
                    current["workflow_id"],
                    current["capture_id"],
                    error.get("code", target.value),
                    error.get("message", target.value),
                )
            return True

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

    def upsert_models(self, models: list[dict[str, Any]], discovered_at: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            for model in models:
                connection.execute(
                    "INSERT INTO model_catalog(name, provider, status, context_window, capabilities_json, discovered_at) "
                    "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(name, provider) DO UPDATE SET status = excluded.status, "
                    "context_window = excluded.context_window, capabilities_json = excluded.capabilities_json, "
                    "discovered_at = excluded.discovered_at",
                    (
                        model["name"],
                        model.get("provider", "unknown"),
                        model["status"],
                        model.get("context_window"),
                        json.dumps(model, ensure_ascii=False),
                        discovered_at,
                    ),
                )

    @staticmethod
    def _fail_workflow(
        connection: sqlite3.Connection,
        workflow_id: str,
        capture_id: str,
        code: str,
        message: str,
    ) -> None:
        connection.execute(
            "UPDATE workflows SET status = 'ERROR', error_code = ?, error_message = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE workflow_id = ?",
            (code, message, workflow_id),
        )
        connection.execute(
            "UPDATE captures SET status = 'FAILED', last_error_code = ?, last_error_message = ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE capture_id = ?",
            (code, message, capture_id),
        )
