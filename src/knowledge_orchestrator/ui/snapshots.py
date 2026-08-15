from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from knowledge_orchestrator.repositories.database import Database

ACTIVE_CAPTURE_STATUSES = ("STAGED", "PENDING", "SUBMITTING", "QUEUED", "PROCESSING")
ACTIVE_TASK_STATUSES = ("READY", "SUBMITTING", "QUEUED", "PROCESSING", "CANCEL_REQUESTED")


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    active_captures: int
    pending_review: int
    failed_captures: int
    published_notes: int
    broker_status: str
    broker_message: str


@dataclass(frozen=True, slots=True)
class QueueItem:
    position: int
    task_id: str
    capture_id: str
    title: str
    status: str
    phase: str
    model: str
    step_kind: str
    sequence_index: int
    completed_steps: int
    total_steps: int
    elapsed_seconds: int
    attempt: int
    execution_strategy: str
    progress_text: str


@dataclass(frozen=True, slots=True)
class WorkItem:
    capture_id: str
    incident_id: int | None
    task_id: str | None
    title: str
    filename: str
    path: str
    status: str
    status_label: str
    category: str
    phase: str
    model: str
    elapsed_seconds: int
    updated_at: str
    updated_label: str
    attempt: int
    error_code: str | None
    error_message: str
    retryable: bool
    progress_text: str


@dataclass(frozen=True, slots=True)
class WorkEvent:
    event_type: str
    message: str
    created_at: str
    created_label: str


@dataclass(frozen=True, slots=True)
class ReviewItem:
    candidate_id: int
    status: str
    relation: str
    confidence: float | None
    impact: str
    target_note_id: int
    rationale: str
    diff_text: str
    blocked_reason: str | None


@dataclass(frozen=True, slots=True)
class TopicItem:
    topic_id: int
    name: str
    folder: str
    position: int
    enabled: bool
    default_profile: str


@dataclass(frozen=True, slots=True)
class ProfileItem:
    profile_id: int
    name: str
    enabled: bool
    preferred_model: str
    execution_strategy: str
    human_review_required: bool
    data_classification: str
    long_context: str
    prompt_compression: str | None
    max_cost_usd: float


class UiSnapshotService:
    """Consultas de solo lectura para la UI de fase 7."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def dashboard(self) -> DashboardSnapshot:
        with closing(self.database.connect(readonly=True)) as connection:
            captures = {
                row["status"]: int(row["total"])
                for row in connection.execute("SELECT status, COUNT(*) AS total FROM captures GROUP BY status")
            }
            pending_review = int(connection.execute(
                "SELECT COUNT(*) FROM update_candidates WHERE status = 'PENDING_REVIEW'"
            ).fetchone()[0])
            published_notes = int(connection.execute(
                "SELECT COUNT(*) FROM notes WHERE status = 'PUBLISHED'"
            ).fetchone()[0])
            broker_event = connection.execute(
                "SELECT event_type, message FROM events WHERE event_type IN "
                "('BROKER_ONLINE', 'BROKER_OFFLINE', 'BROKER_CYCLE_ERROR', 'BROKER_WORKER_CRASH') "
                "ORDER BY created_at DESC, event_id DESC LIMIT 1"
            ).fetchone()
        broker_status = "sin datos"
        broker_message = "Aún no hay health check registrado"
        if broker_event is not None:
            broker_status = "online" if broker_event["event_type"] == "BROKER_ONLINE" else "incidencia"
            broker_message = broker_event["message"]
        return DashboardSnapshot(
            active_captures=sum(captures.get(status, 0) for status in ACTIVE_CAPTURE_STATUSES),
            pending_review=pending_review,
            failed_captures=captures.get("FAILED", 0),
            published_notes=published_notes,
            broker_status=broker_status,
            broker_message=broker_message,
        )

    def queue(self) -> list[QueueItem]:
        placeholders = ",".join("?" for _ in ACTIVE_TASK_STATUSES)
        with closing(self.database.connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT t.task_id, t.capture_id, c.title, t.status, t.step_kind, t.sequence_index, "
                "t.attempt, t.created_at, t.queued_at, t.started_at, t.progress_json, "
                "t.execution_strategy, t.model_used, w.completed_steps, w.total_steps, p.preferred_model "
                "FROM tasks t JOIN captures c ON c.capture_id = t.capture_id "
                "LEFT JOIN workflows w ON w.workflow_id = t.workflow_id "
                "LEFT JOIN profiles p ON p.profile_id = w.profile_id "
                f"WHERE t.status IN ({placeholders}) "
                "ORDER BY COALESCE(t.queued_at, t.created_at), t.sequence_index, t.task_id",
                ACTIVE_TASK_STATUSES,
            ).fetchall()
        return [self._queue_item(position, row) for position, row in enumerate(rows, start=1)]

    def work_items(self) -> list[WorkItem]:
        with closing(self.database.connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT c.capture_id, c.title, c.original_filename, c.status AS capture_status, "
                "c.source_path, c.staging_path, c.processing_path, c.archive_path, "
                "c.rejected_source_path, c.last_error_code, c.last_error_message, c.created_at, "
                "c.updated_at, t.task_id, t.status AS task_status, t.progress_json, t.model_used, "
                "t.error_code AS task_error_code, t.error_message AS task_error_message, "
                "t.error_retryable, t.attempt, t.created_at AS task_created_at, "
                "t.queued_at, t.started_at "
                "FROM captures c LEFT JOIN tasks t ON t.task_id = ("
                "SELECT latest.task_id FROM tasks latest WHERE latest.capture_id = c.capture_id "
                "ORDER BY latest.updated_at DESC, latest.created_at DESC, latest.task_id DESC LIMIT 1"
                ") ORDER BY c.updated_at DESC, c.created_at DESC, c.capture_id DESC"
            ).fetchall()
            incidents = connection.execute(
                "SELECT incident_id, path, filename, error_code, message, created_at, updated_at "
                "FROM ingestion_incidents WHERE status = 'OPEN' ORDER BY updated_at DESC, incident_id DESC"
            ).fetchall()
        items = [self._work_item(row) for row in rows]
        items.extend(self._incident_item(row) for row in incidents)
        return sorted(items, key=lambda item: item.updated_at, reverse=True)

    def work_events(self, capture_id: str, *, limit: int = 8) -> list[WorkEvent]:
        with closing(self.database.connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT event_type, message, created_at FROM events WHERE capture_id = ? "
                "ORDER BY created_at DESC, event_id DESC LIMIT ?",
                (capture_id, max(1, limit)),
            ).fetchall()
        return [
            WorkEvent(
                event_type=str(row["event_type"]),
                message=str(row["message"]),
                created_at=str(row["created_at"]),
                created_label=_clock_label(row["created_at"]),
            )
            for row in reversed(rows)
        ]

    def reviews(self) -> list[ReviewItem]:
        with closing(self.database.connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT candidate_id, status, relation, confidence, impact, target_note_id, rationale, "
                "diff_text, blocked_reason FROM update_candidates "
                "WHERE status = 'PENDING_REVIEW' ORDER BY created_at, candidate_id"
            ).fetchall()
        return [
            ReviewItem(
                candidate_id=int(row["candidate_id"]),
                status=row["status"],
                relation=row["relation"],
                confidence=float(row["confidence"]) if row["confidence"] is not None else None,
                impact=row["impact"] or "",
                target_note_id=int(row["target_note_id"]),
                rationale=row["rationale"] or "",
                diff_text=row["diff_text"] or "",
                blocked_reason=row["blocked_reason"],
            )
            for row in rows
        ]

    def topics(self) -> list[TopicItem]:
        with closing(self.database.connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT t.topic_id, t.name, t.folder, t.position, t.enabled, p.name AS profile_name "
                "FROM topics t LEFT JOIN profiles p ON p.profile_id = t.default_profile_id "
                "ORDER BY t.position, t.topic_id"
            ).fetchall()
        return [
            TopicItem(
                topic_id=int(row["topic_id"]),
                name=row["name"],
                folder=row["folder"],
                position=int(row["position"]),
                enabled=bool(row["enabled"]),
                default_profile=row["profile_name"] or "",
            )
            for row in rows
        ]

    def profiles(self) -> list[ProfileItem]:
        with closing(self.database.connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT profile_id, name, enabled, preferred_model, execution_strategy, human_review_required, "
                "data_classification, long_context, prompt_compression, max_cost_usd "
                "FROM profiles ORDER BY name COLLATE NOCASE, profile_id"
            ).fetchall()
        return [
            ProfileItem(
                profile_id=int(row["profile_id"]),
                name=row["name"],
                enabled=bool(row["enabled"]),
                preferred_model=row["preferred_model"],
                execution_strategy=row["execution_strategy"],
                human_review_required=bool(row["human_review_required"]),
                data_classification=row["data_classification"],
                long_context=row["long_context"],
                prompt_compression=row["prompt_compression"],
                max_cost_usd=float(row["max_cost_usd"]),
            )
            for row in rows
        ]

    def model_names(self) -> list[str]:
        with closing(self.database.connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT name FROM model_catalog WHERE status IN ('available', 'loaded', 'online') "
                "ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [str(row["name"]) for row in rows]

    @staticmethod
    def _queue_item(position: int, row: Any) -> QueueItem:
        progress = _safe_json(row["progress_json"])
        raw_phase = str(progress.get("phase") or progress.get("status") or row["status"]).lower()
        phase = _phase_label(raw_phase)
        started_at = row["started_at"] or row["queued_at"] or row["created_at"]
        model = row["model_used"] or row["preferred_model"] or "auto"
        return QueueItem(
            position=position,
            task_id=row["task_id"],
            capture_id=row["capture_id"],
            title=row["title"],
            status=row["status"],
            phase=phase,
            model=model,
            step_kind=row["step_kind"],
            sequence_index=int(row["sequence_index"]),
            completed_steps=int(row["completed_steps"] or 0),
            total_steps=int(row["total_steps"] or 0),
            elapsed_seconds=_elapsed_seconds(started_at),
            attempt=int(row["attempt"] or 0),
            execution_strategy=row["execution_strategy"] or "single",
            progress_text=(
                "El Broker reanudará la tarea automáticamente cuando haya memoria disponible."
                if raw_phase == "waiting_for_memory"
                else "El Broker iniciará la tarea cuando terminen sus dependencias."
                if raw_phase == "waiting_for_dependencies"
                else _progress_text(progress)
            ),
        )

    @staticmethod
    def _work_item(row: Any) -> WorkItem:
        progress = _safe_json(row["progress_json"])
        task_status = str(row["task_status"] or "")
        capture_status = str(row["capture_status"])
        status = task_status if task_status in ACTIVE_TASK_STATUSES or task_status == "ERROR" else capture_status
        error_code = row["task_error_code"] or row["last_error_code"]
        error_message = str(row["task_error_message"] or row["last_error_message"] or "")
        category = _work_category(capture_status, task_status, error_code)
        phase = str(progress.get("phase") or progress.get("status") or status).lower()
        phase = _phase_label(phase)
        path_candidates = (
            (row["archive_path"], row["processing_path"], row["source_path"], row["staging_path"])
            if capture_status == "COMPLETED"
            else (row["rejected_source_path"], row["archive_path"], row["source_path"])
            if capture_status == "REJECTED"
            else (row["processing_path"], row["staging_path"], row["source_path"], row["archive_path"])
        )
        path = next(
            (
                str(value)
                for value in path_candidates
                if value
            ),
            "",
        )
        started_at = row["started_at"] or row["queued_at"] or row["task_created_at"] or row["created_at"]
        return WorkItem(
            capture_id=str(row["capture_id"]),
            incident_id=None,
            task_id=str(row["task_id"]) if row["task_id"] else None,
            title=str(row["title"]),
            filename=str(row["original_filename"]),
            path=path,
            status=status,
            status_label=_status_label(status, phase),
            category=category,
            phase=phase,
            model=str(row["model_used"] or "Automático"),
            elapsed_seconds=_elapsed_seconds(started_at),
            updated_at=str(row["updated_at"]),
            updated_label=_clock_label(row["updated_at"]),
            attempt=int(row["attempt"] or 0),
            error_code=str(error_code) if error_code else None,
            error_message=error_message,
            retryable=bool(row["error_retryable"]) or task_status == "ERROR",
            progress_text=(
                "El Broker reanudará la tarea automáticamente cuando haya memoria disponible."
                if phase == "Esperando memoria"
                else "El Broker iniciará la tarea cuando terminen sus dependencias."
                if phase == "Esperando dependencias"
                else _progress_text(progress)
            ),
        )

    @staticmethod
    def _incident_item(row: Any) -> WorkItem:
        code = str(row["error_code"])
        label = "Archivo bloqueado" if code == "FILE_LOCKED" else "Archivo inestable"
        return WorkItem(
            capture_id=f"incident:{row['incident_id']}",
            incident_id=int(row["incident_id"]),
            task_id=None,
            title=str(row["filename"]),
            filename=str(row["filename"]),
            path=str(row["path"]),
            status="INGESTION_ERROR",
            status_label=label,
            category="attention",
            phase="Validación de entrada",
            model="—",
            elapsed_seconds=_elapsed_seconds(row["created_at"]),
            updated_at=str(row["updated_at"]),
            updated_label=_clock_label(row["updated_at"]),
            attempt=0,
            error_code=code,
            error_message=str(row["message"]),
            retryable=True,
            progress_text="El archivo sigue en la carpeta vigilada y puede reintentarse de forma segura.",
        )


def _safe_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _progress_text(progress: dict[str, Any]) -> str:
    completed = progress.get("completed")
    total = progress.get("total")
    if isinstance(completed, int) and isinstance(total, int) and total > 0:
        return f"{completed}/{total} unidades"
    current = progress.get("message") or progress.get("detail")
    return str(current) if current else ""


def _elapsed_seconds(value: str | None) -> int:
    if not value:
        return 0
    try:
        started = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds()))


def _work_category(capture_status: str, task_status: str, error_code: str | None) -> str:
    if capture_status in {"COMPLETED", "REJECTED", "CANCELLED"} or task_status == "CANCELLED":
        return "completed"
    if error_code or capture_status == "FAILED" or task_status == "ERROR":
        return "attention"
    return "active"


def _status_label(status: str, phase: str) -> str:
    if phase in {"Esperando memoria", "Esperando dependencias"}:
        return phase
    labels = {
        "STAGED": "Preparando",
        "PENDING": "En cola local",
        "READY": "Listo para enviar",
        "SUBMITTING": "Enviando",
        "QUEUED": "En cola del Broker",
        "PROCESSING": "Procesando",
        "CANCEL_REQUESTED": "Cancelando",
        "SUCCESS": "Procesado",
        "COMPLETED": "Completado",
        "FAILED": "Error",
        "ERROR": "Error",
        "REJECTED": "Rechazado",
        "CANCELLED": "Cancelado",
    }
    return labels.get(status, status.replace("_", " ").capitalize())


def _phase_label(phase: str) -> str:
    return {
        "waiting_for_memory": "Esperando memoria",
        "waiting_for_dependencies": "Esperando dependencias",
    }.get(phase, phase)


def _clock_label(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return parsed.astimezone().strftime("%H:%M:%S")
