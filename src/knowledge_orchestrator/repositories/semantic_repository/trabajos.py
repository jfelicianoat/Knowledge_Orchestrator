"""Trabajos semánticos contra el Broker: cola, envío, estado y recuperación."""
from __future__ import annotations

import json
from contextlib import closing

from knowledge_orchestrator.domain.semantic_models import (
    SemanticJob,
)
from knowledge_orchestrator.repositories.semantic_repository.candidatos import CandidatosMixin
from knowledge_orchestrator.repositories.semantic_repository.filas import _job


class TrabajosMixin(CandidatosMixin):
    """Cola durable de trabajos semánticos."""

    @staticmethod
    def _audit_job_transition(connection, job_id: str, previous: str | None, action: str) -> None:
        row = connection.execute('SELECT job_id,kind,note_id,candidate_id,broker_task_id,status,attempt '
                                 'FROM semantic_jobs WHERE job_id=?', (job_id,)).fetchone()
        if row is None or row['status'] == previous:
            return
        details = {**dict(row), 'from_status': previous, 'action': action, 'actor': 'orchestrator:semantic'}
        connection.execute('INSERT INTO events(event_type,message,details_json) VALUES (?,?,?)',
                           ('SEMANTIC_JOB_STATE_CHANGED', 'Transición de análisis semántico', json.dumps(details)))

    def create_job(
        self,
        *,
        job_id: str,
        kind: str,
        idempotency_key: str,
        request: dict,
        note_id: int | None = None,
        candidate_id: int | None = None,
    ) -> SemanticJob:
        with self.database.transaction(immediate=True) as connection:
            inserted = connection.execute(
                "INSERT INTO semantic_jobs(job_id, kind, note_id, candidate_id, idempotency_key, request_json) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(job_id) DO NOTHING",
                (job_id, kind, note_id, candidate_id, idempotency_key, json.dumps(request, ensure_ascii=False)),
            )
            if inserted.rowcount:
                self._audit_job_transition(connection, job_id, None, 'created')
            return _job(connection.execute("SELECT * FROM semantic_jobs WHERE job_id = ?", (job_id,)).fetchone())

    def list_dispatchable_jobs(self) -> list[SemanticJob]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM semantic_jobs WHERE status = 'READY' AND "
                "(next_retry_at IS NULL OR next_retry_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) "
                "ORDER BY created_at, job_id"
            ).fetchall()
            return [_job(row) for row in rows]

    def get_job(self, job_id: str) -> SemanticJob | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute("SELECT * FROM semantic_jobs WHERE job_id = ?", (job_id,)).fetchone()
            return _job(row) if row else None

    def claim_job(self, job_id: str) -> SemanticJob | None:
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE semantic_jobs SET status = 'SUBMITTING', attempt = attempt + 1, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE job_id = ? AND status = 'READY'",
                (job_id,),
            )
            if cursor.rowcount != 1:
                return None
            self._audit_job_transition(connection, job_id, 'READY', 'submission_started')
            return _job(connection.execute("SELECT * FROM semantic_jobs WHERE job_id = ?", (job_id,)).fetchone())

    def accept_job(self, job_id: str, response: dict) -> None:
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute(
                "UPDATE semantic_jobs SET status = 'QUEUED', broker_task_id = ?, status_url = ?, next_retry_at = NULL, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE job_id = ? AND status = 'SUBMITTING'",
                (response["task_id"], response["status_url"], job_id),
            )
            if changed.rowcount:
                self._audit_job_transition(connection, job_id, 'SUBMITTING', 'accepted')

    def retry_job(self, job_id: str, *, next_retry_at: str, message: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute(
                "UPDATE semantic_jobs SET status = 'READY', next_retry_at = ?, error_code = 'BROKER_UNAVAILABLE', "
                "error_message = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE job_id = ? AND status = 'SUBMITTING'",
                (next_retry_at, message, job_id),
            )
            if changed.rowcount:
                self._audit_job_transition(connection, job_id, 'SUBMITTING', 'retry_scheduled')

    def fail_job(self, job_id: str, code: str, message: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            prior = connection.execute('SELECT status FROM semantic_jobs WHERE job_id=?', (job_id,)).fetchone()
            changed = connection.execute(
                "UPDATE semantic_jobs SET status = 'ERROR', error_code = ?, error_message = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE job_id = ? "
                "AND status NOT IN ('SUCCESS', 'ERROR')",
                (code, message, job_id),
            )
            if changed.rowcount:
                self._audit_job_transition(connection, job_id, prior['status'], 'failed')

    def list_active_jobs(self) -> list[SemanticJob]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM semantic_jobs WHERE status IN ('QUEUED', 'PROCESSING') ORDER BY created_at"
            ).fetchall()
            return [_job(row) for row in rows]

    def update_job_status(self, job_id: str, payload: dict) -> tuple[SemanticJob, str | None] | None:
        broker_status = payload["status"]
        if broker_status in {"queued", "waiting_for_memory", "waiting_for_dependencies"}:
            target = "QUEUED"
        elif broker_status in {"completed", "success"}:
            target = "SUCCESS"
        elif broker_status in {"failed", "error", "cancelled"}:
            target = "ERROR"
        else:
            # Todas las fases no terminales, incluidas las que el Broker añada
            # en el futuro, se tratan como trabajo en curso.
            target = "PROCESSING"
        with self.database.transaction(immediate=True) as connection:
            current = connection.execute("SELECT * FROM semantic_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if current is None or current["status"] in {"SUCCESS", "ERROR"}:
                return None
            result_text = None
            error = payload.get("error") or {}
            if target == "SUCCESS":
                result = payload.get("result") or {}
                result_text = result.get("result_markdown") or result.get("assistant_content")
                if not isinstance(result_text, str) or not result_text.strip():
                    raise ValueError("Resultado semántico vacío")
            connection.execute(
                "UPDATE semantic_jobs SET status = ?, result_json = ?, error_code = ?, error_message = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE job_id = ?",
                (
                    "PROCESSING" if target == "SUCCESS" else target,
                    json.dumps(payload.get("result"), ensure_ascii=False) if target == "SUCCESS" else None,
                    error.get("code") if target == "ERROR" else None,
                    error.get("message") if target == "ERROR" else None,
                    job_id,
                ),
            )
            refreshed = connection.execute("SELECT * FROM semantic_jobs WHERE job_id = ?", (job_id,)).fetchone()
            self._audit_job_transition(connection, job_id, current['status'], 'broker_status_received')
            return _job(refreshed), result_text

    def complete_job(self, job_id: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute(
                "UPDATE semantic_jobs SET status = 'SUCCESS', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE job_id = ? AND status = 'PROCESSING' AND result_json IS NOT NULL",
                (job_id,),
            )
            if changed.rowcount:
                self._audit_job_transition(connection, job_id, 'PROCESSING', 'result_integrated')

    def recover_jobs(self) -> None:
        with self.database.transaction(immediate=True) as connection:
            interrupted = connection.execute("SELECT job_id FROM semantic_jobs WHERE status='SUBMITTING'").fetchall()
            connection.execute(
                "UPDATE semantic_jobs SET status = 'READY', next_retry_at = NULL, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE status = 'SUBMITTING'"
            )
            for row in interrupted:
                self._audit_job_transition(connection, row['job_id'], 'SUBMITTING', 'submission_recovered')
