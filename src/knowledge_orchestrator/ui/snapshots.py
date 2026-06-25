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


class UiSnapshotService:
    """Consultas de solo lectura para la UI de fase 7."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def dashboard(self) -> DashboardSnapshot:
        with closing(self.database.connect()) as connection:
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
        with closing(self.database.connect()) as connection:
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

    def reviews(self) -> list[ReviewItem]:
        with closing(self.database.connect()) as connection:
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
        with closing(self.database.connect()) as connection:
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
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT profile_id, name, enabled, preferred_model, execution_strategy, human_review_required "
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
            )
            for row in rows
        ]

    @staticmethod
    def _queue_item(position: int, row: Any) -> QueueItem:
        progress = _safe_json(row["progress_json"])
        phase = str(progress.get("phase") or progress.get("status") or row["status"]).lower()
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
            progress_text=_progress_text(progress),
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
