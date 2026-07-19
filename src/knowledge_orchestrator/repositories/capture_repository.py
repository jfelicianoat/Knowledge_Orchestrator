from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from typing import Any

from knowledge_orchestrator.domain.models import CaptureRecord, CaptureStatus, SourceOrigin

from .database import Database


def _path(value: str | None) -> Path | None:
    return Path(value) if value else None


def _record(row: sqlite3.Row) -> CaptureRecord:
    return CaptureRecord(
        capture_id=row["capture_id"],
        contract_version=row["contract_version"],
        source_type=row["source_type"],
        title=row["title"],
        status=CaptureStatus(row["status"]),
        source_path=_path(row["source_path"]),
        staging_path=_path(row["staging_path"]),
        processing_path=_path(row["processing_path"]),
        sha256=row["sha256"],
        original_filename=row["original_filename"],
        metadata_json=row["metadata_json"],
        transcript_content=row["transcript_content"],
        last_error_code=row["last_error_code"],
        last_error_message=row["last_error_message"],
        source_origin=SourceOrigin(row["source_origin"]),
        topic_id=row["topic_id"],
        profile_id=row["profile_id"],
        obsolescence_date=row["obsolescence_date"],
        domain_enriched_at=row["domain_enriched_at"],
        archive_path=_path(row["archive_path"]),
        rejected_source_path=_path(row["rejected_source_path"]),
    )


class CaptureRepository:
    _UPDATABLE_COLUMNS = {
        "source_path",
        "staging_path",
        "processing_path",
        "last_error_code",
        "last_error_message",
    }

    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, capture_id: str) -> CaptureRecord | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute("SELECT * FROM captures WHERE capture_id = ?", (capture_id,)).fetchone()
            return _record(row) if row else None

    def count(self) -> int:
        with closing(self.database.connect()) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM captures").fetchone()[0])

    def list_by_status(self, statuses: Iterable[CaptureStatus]) -> list[CaptureRecord]:
        values = [status.value for status in statuses]
        if not values:
            return []
        placeholders = ",".join("?" for _ in values)
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                f"SELECT * FROM captures WHERE status IN ({placeholders}) ORDER BY created_at, capture_id",
                values,
            ).fetchall()
            return [_record(row) for row in rows]

    def list_unenriched_pending(self) -> list[CaptureRecord]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM captures WHERE status = 'PENDING' AND domain_enriched_at IS NULL "
                "ORDER BY created_at, capture_id"
            ).fetchall()
            return [_record(row) for row in rows]

    def insert_staged(self, record: CaptureRecord) -> None:
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO captures (capture_id, contract_version, source_type, title, status, "
                "source_path, staging_path, processing_path, sha256, original_filename, metadata_json, "
                "transcript_content, last_error_code, last_error_message) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.capture_id,
                    record.contract_version,
                    record.source_type,
                    record.title,
                    record.status.value,
                    str(record.source_path) if record.source_path else None,
                    str(record.staging_path) if record.staging_path else None,
                    str(record.processing_path) if record.processing_path else None,
                    record.sha256,
                    record.original_filename,
                    record.metadata_json,
                    record.transcript_content,
                    record.last_error_code,
                    record.last_error_message,
                ),
            )
            self._insert_event(connection, record.capture_id, "CAPTURE_STAGED", "Captura confirmada en staging", {})

    def transition(
        self,
        capture_id: str,
        expected: CaptureStatus,
        target: CaptureStatus,
        **updates: str | Path | None,
    ) -> None:
        unknown = set(updates) - self._UPDATABLE_COLUMNS
        if unknown:
            raise ValueError(f"Columnas no actualizables: {sorted(unknown)}")
        assignments = ["status = ?", "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"]
        values: list[Any] = [target.value]
        for column, value in updates.items():
            assignments.append(f"{column} = ?")
            values.append(str(value) if isinstance(value, Path) else value)
        values.extend([capture_id, expected.value])
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                f"UPDATE captures SET {', '.join(assignments)} WHERE capture_id = ? AND status = ?",
                values,
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"Transición inválida para {capture_id}: se esperaba {expected.value}"
                )
            self._insert_event(
                connection,
                capture_id,
                f"CAPTURE_{target.value}",
                f"Transición {expected.value} -> {target.value}",
                updates,
            )

    def mark_pending(self, capture_id: str, processing_path: Path) -> None:
        self.transition(
            capture_id,
            CaptureStatus.STAGED,
            CaptureStatus.PENDING,
            processing_path=processing_path,
            staging_path=None,
            last_error_code=None,
            last_error_message=None,
        )

    def mark_failed(self, capture_id: str, expected: CaptureStatus, code: str, message: str) -> None:
        self.transition(
            capture_id,
            expected,
            CaptureStatus.FAILED,
            last_error_code=code,
            last_error_message=message,
        )

    def record_event(
        self,
        event_type: str,
        message: str,
        *,
        capture_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        with self.database.transaction(immediate=True) as connection:
            self._insert_event(connection, capture_id, event_type, message, details or {})

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        capture_id: str | None,
        event_type: str,
        message: str,
        details: dict[str, Any],
    ) -> None:
        connection.execute(
            "INSERT INTO events(capture_id, event_type, message, details_json) VALUES (?, ?, ?, ?)",
            (capture_id, event_type, message, json.dumps(details, ensure_ascii=False, default=str)),
        )
