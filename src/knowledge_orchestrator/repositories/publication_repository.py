from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from knowledge_orchestrator.domain.publication_models import (
    DraftForReview,
    NoteRecord,
    PublishableWorkflow,
    ReprocessIntent,
)

from .database import Database


def _note(row: sqlite3.Row) -> NoteRecord:
    return NoteRecord(
        note_id=int(row["note_id"]), capture_id=row["capture_id"], workflow_id=row["workflow_id"],
        revision=int(row["revision"]), status=row["status"], vault_path=Path(row["vault_path"]),
        temp_path=Path(row["temp_path"]) if row["temp_path"] else None,
        content_hash=row["content_hash"], rejected_path=Path(row["rejected_path"]) if row["rejected_path"] else None,
        source_archive_path=Path(row["source_archive_path"]),
    )


def result_hash(final_result: str) -> str:
    """Identidad del resultado revisado: se aprueba este texto, no «el que haya»."""

    return hashlib.sha256(final_result.encode("utf-8")).hexdigest()


def _review_allows(row: sqlite3.Row) -> bool:
    if not row["review_required"]:
        return True
    return bool(row["review_result_hash"]) and row["review_result_hash"] == result_hash(row["final_result"])


def _intent(row: sqlite3.Row) -> ReprocessIntent:
    return ReprocessIntent(
        intent_id=int(row["intent_id"]), capture_id=row["capture_id"], source_note_id=int(row["source_note_id"]),
        revision=int(row["revision"]), source_path=Path(row["source_path"]), target_path=Path(row["target_path"]),
        status=row["status"],
    )


class PublicationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_publishable(self) -> list[PublishableWorkflow]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT w.workflow_id, w.capture_id, w.revision, w.final_result, w.profile_id, "
                "c.topic_id, w.updated_at, w.review_required, w.review_result_hash "
                "FROM workflows w JOIN captures c ON c.capture_id = w.capture_id "
                "LEFT JOIN notes n ON n.workflow_id = w.workflow_id "
                "WHERE w.status = 'SUCCESS' AND w.final_result IS NOT NULL AND n.note_id IS NULL "
                # Un borrador que exige revisión solo se publica aprobado, y
                # aprobado sobre este mismo resultado (se comprueba el hash abajo).
                "AND (w.review_required = 0 OR w.review_status = 'APPROVED') "
                "ORDER BY w.updated_at, w.workflow_id"
            ).fetchall()
            return [PublishableWorkflow(
                workflow_id=row["workflow_id"], capture_id=row["capture_id"], revision=int(row["revision"]),
                final_result=row["final_result"], profile_id=int(row["profile_id"]), topic_id=int(row["topic_id"]),
                processed_at=row["updated_at"],
            ) for row in rows if _review_allows(row)]

    def create_intent(
        self, workflow: PublishableWorkflow, *, vault_path: Path, temp_path: Path,
        content_hash: str, source_archive_path: Path,
    ) -> NoteRecord:
        with self.database.transaction(immediate=True) as connection:
            existing = connection.execute(
                "SELECT * FROM notes WHERE workflow_id = ?", (workflow.workflow_id,)
            ).fetchone()
            if existing:
                return _note(existing)
            cursor = connection.execute(
                "INSERT INTO notes(capture_id, revision, vault_path, status, workflow_id, topic_id, profile_id, "
                "temp_path, content_hash, source_archive_path) VALUES (?, ?, ?, 'PUBLISHING', ?, ?, ?, ?, ?, ?)",
                (workflow.capture_id, workflow.revision, str(vault_path), workflow.workflow_id, workflow.topic_id,
                 workflow.profile_id, str(temp_path), content_hash, str(source_archive_path)),
            )
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) VALUES (?, 'PUBLICATION_PREPARED', "
                "'Intención de publicación persistida', '{}')", (workflow.capture_id,),
            )
            return _note(connection.execute("SELECT * FROM notes WHERE note_id = ?", (cursor.lastrowid,)).fetchone())

    def get_note(self, note_id: int) -> NoteRecord | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute("SELECT * FROM notes WHERE note_id = ?", (note_id,)).fetchone()
            return _note(row) if row else None

    def get_workflow_for_note(self, note_id: int) -> PublishableWorkflow:
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT w.workflow_id, w.capture_id, w.revision, w.final_result, w.profile_id, "
                "c.topic_id, w.updated_at "
                "FROM notes n JOIN workflows w ON w.workflow_id = n.workflow_id "
                "JOIN captures c ON c.capture_id = w.capture_id WHERE n.note_id = ?", (note_id,)
            ).fetchone()
            if row is None or row["final_result"] is None:
                raise ValueError("La nota no tiene un workflow publicable")
            return PublishableWorkflow(
                workflow_id=row["workflow_id"], capture_id=row["capture_id"], revision=int(row["revision"]),
                final_result=row["final_result"], profile_id=int(row["profile_id"]), topic_id=int(row["topic_id"]),
                processed_at=row["updated_at"],
            )

    def fail_publication(self, workflow: PublishableWorkflow, message: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE workflows SET status = 'ERROR', error_code = 'INVALID_RESULT_MARKDOWN', error_message = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE workflow_id = ? AND status = 'SUCCESS'",
                (message, workflow.workflow_id),
            )
            connection.execute(
                "UPDATE captures SET status = 'FAILED', last_error_code = 'INVALID_RESULT_MARKDOWN', "
                "last_error_message = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE capture_id = ?", (message, workflow.capture_id),
            )
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) VALUES (?, "
                "'PUBLICATION_FAILED', ?, '{}')", (workflow.capture_id, message),
            )

    def list_notes_by_status(self, *statuses: str) -> list[NoteRecord]:
        if not statuses:
            return []
        marks = ",".join("?" for _ in statuses)
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                f"SELECT * FROM notes WHERE status IN ({marks}) ORDER BY note_id", statuses
            ).fetchall()
            return [_note(row) for row in rows]

    def mark_published(self, note_id: int) -> None:
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE notes SET status = 'PUBLISHED', temp_path = NULL, published_at = "
                "COALESCE(published_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE note_id = ? "
                "AND status IN ('PUBLISHING','CONFLICT')",
                (note_id,),
            )

    def conflict_publication(self, note_id: int) -> None:
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute(
                "UPDATE notes SET status='CONFLICT', updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                "WHERE note_id=? AND status='PUBLISHING'", (note_id,),
            )
            if not changed.rowcount:
                return
            row = connection.execute("SELECT capture_id FROM notes WHERE note_id=?", (note_id,)).fetchone()
            message = "La nota destino cambió. Conserve o mueva su edición antes de reintentar la publicación."
            connection.execute(
                "UPDATE captures SET last_error_code='PUBLICATION_CONFLICT',last_error_message=?, "
                "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE capture_id=?",
                (message, row['capture_id']),
            )
            connection.execute(
                "INSERT INTO events(capture_id,event_type,message,details_json) "
                "VALUES (?,'PUBLICATION_CONFLICT',?,json_object('note_id',?))",
                (row['capture_id'], message, note_id),
            )

    def complete_capture(self, note_id: int) -> None:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT capture_id, source_archive_path FROM notes WHERE note_id = ?", (note_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Nota inexistente")
            connection.execute(
                "UPDATE captures SET status = 'COMPLETED', archive_path = ?, processing_path = NULL, "
                "last_error_message = CASE WHEN last_error_code='PUBLICATION_CONFLICT' THEN NULL "
                "ELSE last_error_message END, "
                "last_error_code = CASE WHEN last_error_code='PUBLICATION_CONFLICT' THEN NULL "
                "ELSE last_error_code END, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE capture_id = ? "
                "AND status IN ('PROCESSING', 'COMPLETED')",
                (row["source_archive_path"], row["capture_id"]),
            )
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) VALUES (?, 'CAPTURE_COMPLETED', "
                "'Nota publicada y fuente archivada', '{}')", (row["capture_id"],),
            )

    def prepare_rejection(self, note_id: int, *, rejected_note: Path, rejected_source: Path) -> NoteRecord:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute("SELECT * FROM notes WHERE note_id = ?", (note_id,)).fetchone()
            if row is None or row["status"] not in {"PUBLISHED", "REJECTING"}:
                raise ValueError("Solo se puede rechazar una nota publicada")
            connection.execute(
                "UPDATE notes SET status = 'REJECTING', rejected_path = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE note_id = ?",
                (str(rejected_note), note_id),
            )
            connection.execute(
                "UPDATE captures SET rejected_source_path = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE capture_id = ?", (str(rejected_source), row["capture_id"]),
            )
            return _note(connection.execute("SELECT * FROM notes WHERE note_id = ?", (note_id,)).fetchone())

    def complete_rejection(self, note_id: int) -> None:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute("SELECT capture_id FROM notes WHERE note_id = ?", (note_id,)).fetchone()
            if row is None:
                raise ValueError("Nota inexistente")
            connection.execute(
                "UPDATE notes SET status = 'REJECTED', rejected_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE note_id = ? AND status = 'REJECTING'",
                (note_id,),
            )
            connection.execute(
                "UPDATE captures SET status = 'REJECTED', archive_path = NULL, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE capture_id = ? AND status = 'COMPLETED'",
                (row["capture_id"],),
            )
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) VALUES (?, 'NOTE_REJECTED', "
                "'Nota y fuente conservadas en rejected', '{}')", (row["capture_id"],),
            )

    def next_revision(self, capture_id: str) -> int:
        with closing(self.database.connect()) as connection:
            return int(connection.execute(
                "SELECT COALESCE(MAX(revision), 0) + 1 FROM workflows WHERE capture_id = ?", (capture_id,)
            ).fetchone()[0])

    def create_reprocess_intent(
        self, capture_id: str, source_note_id: int, revision: int, source_path: Path, target_path: Path,
    ) -> ReprocessIntent:
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO reprocess_intents(capture_id, source_note_id, revision, source_path, target_path, status) "
                "VALUES (?, ?, ?, ?, ?, 'PREPARED') ON CONFLICT(capture_id, revision) DO NOTHING",
                (capture_id, source_note_id, revision, str(source_path), str(target_path)),
            )
            row = connection.execute(
                "SELECT * FROM reprocess_intents WHERE capture_id = ? AND revision = ?", (capture_id, revision)
            ).fetchone()
            return _intent(row)

    def list_reprocess_intents(self, *statuses: str) -> list[ReprocessIntent]:
        marks = ",".join("?" for _ in statuses)
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                f"SELECT * FROM reprocess_intents WHERE status IN ({marks}) ORDER BY intent_id", statuses
            ).fetchall()
            return [_intent(row) for row in rows]

    def mark_reprocess_copied(self, intent_id: int, target_path: Path) -> None:
        with self.database.transaction(immediate=True) as connection:
            intent = connection.execute("SELECT * FROM reprocess_intents WHERE intent_id = ?", (intent_id,)).fetchone()
            connection.execute(
                "UPDATE captures SET status = 'PENDING', processing_path = ?, archive_path = NULL, "
                "last_error_code = NULL, last_error_message = NULL, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE capture_id = ? AND status IN ('REJECTED', 'PENDING')",
                (str(target_path), intent["capture_id"]),
            )
            connection.execute(
                "UPDATE reprocess_intents SET status = 'COPIED', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE intent_id = ? AND status IN ('PREPARED', 'COPIED')", (intent_id,),
            )

    def mark_reprocess_planned(self, intent_id: int) -> None:
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE reprocess_intents SET status = 'PLANNED', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE intent_id = ? AND status = 'COPIED'", (intent_id,),
            )

    # ------------------------------------------------------ borradores (H01)

    def get_draft(self, capture_id: str) -> DraftForReview | None:
        """El borrador revisable (pendiente o descartado) más reciente de una captura."""

        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT w.workflow_id, w.capture_id, w.revision, w.final_result, w.updated_at, "
                "w.review_status, c.title FROM workflows w JOIN captures c ON c.capture_id = w.capture_id "
                "WHERE w.capture_id = ? AND w.status = 'SUCCESS' AND w.review_required = 1 "
                "AND w.review_status IN ('PENDING', 'REJECTED') AND w.final_result IS NOT NULL "
                "ORDER BY w.revision DESC LIMIT 1",
                (capture_id,),
            ).fetchone()
        if row is None:
            return None
        return DraftForReview(
            workflow_id=row["workflow_id"], capture_id=row["capture_id"], title=row["title"],
            revision=int(row["revision"]), final_result=row["final_result"],
            result_hash=result_hash(row["final_result"]), review_status=row["review_status"],
            finished_at=row["updated_at"],
        )

    def approve_draft(self, workflow_id: str, expected_hash: str, *, actor: str = "user:desktop") -> bool:
        """Aprueba el borrador que se revisó. Si el texto cambió, no aprueba nada."""

        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT capture_id, final_result FROM workflows WHERE workflow_id = ? AND status = 'SUCCESS' "
                "AND review_required = 1 AND review_status = 'PENDING'",
                (workflow_id,),
            ).fetchone()
            if row is None or result_hash(row["final_result"]) != expected_hash:
                return False
            connection.execute(
                "UPDATE workflows SET review_status = 'APPROVED', review_result_hash = ?, "
                "reviewed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE workflow_id = ?",
                (expected_hash, workflow_id),
            )
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) "
                "VALUES (?, 'DRAFT_APPROVED', 'Borrador aprobado; se publicará en la bóveda', ?)",
                (row["capture_id"], json.dumps({"workflow_id": workflow_id, "result_hash": expected_hash,
                                                 "actor": actor})),
            )
            return True

    def reject_draft(self, workflow_id: str, *, actor: str = "user:desktop") -> bool:
        """Descarta el borrador. La fuente sigue en processing y el resultado en SQLite."""

        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT capture_id FROM workflows WHERE workflow_id = ? AND status = 'SUCCESS' "
                "AND review_required = 1 AND review_status = 'PENDING'",
                (workflow_id,),
            ).fetchone()
            if row is None:
                return False
            connection.execute(
                "UPDATE workflows SET review_status = 'REJECTED', "
                "reviewed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE workflow_id = ?",
                (workflow_id,),
            )
            connection.execute(
                "UPDATE captures SET status = 'REJECTED', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE capture_id = ? AND status = 'PROCESSING'",
                (row["capture_id"],),
            )
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) "
                "VALUES (?, 'DRAFT_REJECTED', 'Borrador descartado; la fuente y el resultado se conservan', ?)",
                (row["capture_id"], json.dumps({"workflow_id": workflow_id, "actor": actor})),
            )
            return True

    def reopen_rejected_draft(self, capture_id: str) -> bool:
        """Deja la captura de un borrador descartado lista para planificar otra revisión."""

        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT c.processing_path FROM captures c WHERE c.capture_id = ? AND c.status = 'REJECTED' "
                "AND EXISTS (SELECT 1 FROM workflows w WHERE w.capture_id = c.capture_id "
                "AND w.review_status = 'REJECTED') "
                "AND NOT EXISTS (SELECT 1 FROM notes n WHERE n.capture_id = c.capture_id)",
                (capture_id,),
            ).fetchone()
            if row is None or not row["processing_path"]:
                return False
            connection.execute(
                "UPDATE captures SET status = 'PENDING', last_error_code = NULL, last_error_message = NULL, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE capture_id = ?",
                (capture_id,),
            )
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) "
                "VALUES (?, 'DRAFT_REPROCESS_REQUESTED', 'Se vuelve a procesar el documento', '{}')",
                (capture_id,),
            )
            return True

    # ------------------------------------------------------- incidencias

    def record_publication_incident(self, workflow: PublishableWorkflow, error: Exception) -> None:
        self.record_capture_incident(workflow.capture_id, "PUBLICATION_DEFERRED", error)

    def record_note_incident(self, note: NoteRecord, code: str, error: Exception) -> None:
        self.record_capture_incident(note.capture_id, code, error, note_id=note.note_id)

    def record_capture_incident(
        self, capture_id: str, code: str, error: Exception, *, note_id: int | None = None,
    ) -> None:
        """Deja constancia sin repetirla en cada ciclo: solo si el mensaje cambió."""

        message = f"{type(error).__name__}: {error}"[:500]
        with self.database.transaction(immediate=True) as connection:
            last = connection.execute(
                "SELECT message FROM events WHERE capture_id = ? AND event_type = ? "
                "ORDER BY event_id DESC LIMIT 1",
                (capture_id, code),
            ).fetchone()
            if last is not None and last["message"] == message:
                return
            connection.execute(
                "INSERT INTO events(capture_id, event_type, message, details_json) VALUES (?, ?, ?, ?)",
                (capture_id, code, message, json.dumps({"note_id": note_id})),
            )
