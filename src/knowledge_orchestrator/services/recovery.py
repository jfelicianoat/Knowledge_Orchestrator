from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.domain.contracts import parse_capture_bytes
from knowledge_orchestrator.domain.errors import CaptureContractError
from knowledge_orchestrator.domain.models import CaptureDocument, CaptureRecord, CaptureStatus
from knowledge_orchestrator.repositories.capture_repository import CaptureRepository

from .filesystem import unique_destination, write_synced
from .ingestion import IngestionService
from .quarantine import QuarantineService


@dataclass(slots=True)
class RecoveryReport:
    quarantines_recovered: int = 0
    staged_completed: int = 0
    pending_repaired: int = 0
    orphan_staging_recovered: int = 0
    orphan_processing_recovered: int = 0
    inbox_ingested: int = 0
    failed: int = 0


class RecoveryService:
    """Recompone SQLite y carpetas de trabajo despues de una caida.

    La idea es sencilla pero delicada: no adivinamos. Cada fichero se verifica por
    hash y capture_id antes de adoptarlo, moverlo o retirar el original del inbox.
    """

    def __init__(
        self,
        paths: PipelinePaths,
        repository: CaptureRepository,
        *,
        ingestion_service: IngestionService | None = None,
    ) -> None:
        self.paths = paths
        self.repository = repository
        self.ingestion_service = ingestion_service
        self.quarantine = QuarantineService(paths, repository)

    def recover(self, *, ingest_inbox: bool = False) -> RecoveryReport:
        """Ejecuta una pasada de reconciliacion sin duplicar capturas ni tareas."""

        self.paths.ensure_directories()
        report = RecoveryReport()
        report.quarantines_recovered = self.quarantine.recover_pending()
        # Primero rematamos capturas con estado durable conocido; los huerfanos vienen despues.
        for record in self.repository.list_by_status([CaptureStatus.STAGED]):
            try:
                self._complete_staged(record)
                report.staged_completed += 1
            except Exception as error:
                self._fail_capture(
                    record.capture_id,
                    "STAGING_RECOVERY_FAILED",
                    str(error),
                )
                report.failed += 1

        for record in self.repository.list_by_status([CaptureStatus.PENDING]):
            try:
                self._repair_pending(record)
                report.pending_repaired += 1
            except Exception as error:
                self._fail_capture(
                    record.capture_id,
                    "PROCESSING_FILE_MISSING",
                    str(error),
                )
                report.failed += 1

        for staging_path in sorted(self.paths.staging.glob("*.part")):
            try:
                document = parse_capture_bytes(staging_path.read_bytes())
                existing = self.repository.get(document.capture_id)
                if existing is None:
                    # Si no hay fila SQLite pero el fichero valida, lo adoptamos con hash nuevo.
                    self._adopt_orphan(staging_path, document, from_processing=False)
                    report.orphan_staging_recovered += 1
                elif hashlib.sha256(staging_path.read_bytes()).hexdigest() == existing.sha256:
                    staging_path.unlink()
                else:
                    raise ValueError("Staging huérfano conflictivo con SQLite")
            except Exception as error:
                self._quarantine_orphan(staging_path, "ORPHAN_STAGING_INVALID", str(error))
                report.failed += 1

        known_processing = {
            record.processing_path.resolve()
            for record in self.repository.list_by_status([CaptureStatus.PENDING])
            if record.processing_path and record.processing_path.exists()
        }
        for processing_path in sorted(self.paths.processing.glob("*.md")):
            if processing_path.resolve() in known_processing:
                continue
            try:
                document = parse_capture_bytes(processing_path.read_bytes())
                if self.repository.get(document.capture_id) is None:
                    self._adopt_orphan(processing_path, document, from_processing=True)
                    report.orphan_processing_recovered += 1
            except Exception as error:
                self._quarantine_orphan(processing_path, "ORPHAN_PROCESSING_INVALID", str(error))
                report.failed += 1

        if ingest_inbox:
            if self.ingestion_service is None:
                raise RuntimeError("Se necesita IngestionService para procesar inbox al arrancar")
            for source_path in sorted(self.paths.inbox.glob("*.md")):
                result = self.ingestion_service.ingest(source_path)
                if result.accepted:
                    report.inbox_ingested += 1
        return report

    def _fail_capture(self, capture_id: str, code: str, message: str) -> None:
        current = self.repository.get(capture_id)
        if current and current.status in {CaptureStatus.STAGED, CaptureStatus.PENDING}:
            self.repository.mark_failed(capture_id, current.status, code, message)
            return
        self.repository.record_event(
            code,
            message,
            capture_id=capture_id if current else None,
            details={"capture_id": capture_id},
        )

    def _complete_staged(self, record: CaptureRecord) -> None:
        processing = record.processing_path or self.paths.processing / record.original_filename
        if processing.exists():
            self._verify(processing, record)
        elif record.staging_path and record.staging_path.exists():
            self._verify(record.staging_path, record)
            processing.parent.mkdir(parents=True, exist_ok=True)
            # El registro STAGED ya existe; este replace solo completa el paso fisico pendiente.
            os.replace(record.staging_path, processing)
        elif record.source_path and record.source_path.exists():
            source_bytes = record.source_path.read_bytes()
            self._verify_bytes(source_bytes, record)
            staging = record.staging_path or self.paths.staging / f"{record.capture_id}.part"
            write_synced(staging, source_bytes)
            processing.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, processing)
        else:
            raise FileNotFoundError("No existe staging, processing ni inbox para la captura STAGED")
        self.repository.mark_pending(record.capture_id, processing)
        self._retire_source(record.source_path, record.sha256)

    def _repair_pending(self, record: CaptureRecord) -> None:
        processing = record.processing_path or self.paths.processing / record.original_filename
        if processing.exists():
            self._verify(processing, record)
        elif record.staging_path and record.staging_path.exists():
            self._verify(record.staging_path, record)
            os.replace(record.staging_path, processing)
        elif record.source_path and record.source_path.exists():
            source_bytes = record.source_path.read_bytes()
            self._verify_bytes(source_bytes, record)
            write_synced(processing, source_bytes)
        else:
            raise FileNotFoundError("No existe el fichero processing de una captura PENDING")
        self._retire_source(record.source_path, record.sha256)

    def _adopt_orphan(self, path: Path, document: CaptureDocument, *, from_processing: bool) -> None:
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        source = self._find_inbox_by_hash(digest)
        capture_id = document.capture_id
        original_filename = source.name if source else f"{capture_id}.md"
        processing = path if from_processing else unique_destination(
            self.paths.processing, original_filename, capture_id
        )
        record = CaptureRecord(
            capture_id=capture_id,
            contract_version=document.contract_version,
            source_type=document.source_type,
            title=document.title,
            status=CaptureStatus.STAGED,
            source_path=source,
            staging_path=None if from_processing else path,
            processing_path=processing,
            sha256=digest,
            original_filename=original_filename,
            metadata_json=json.dumps(dict(document.metadata), ensure_ascii=False, sort_keys=True, default=str),
            transcript_content=document.transcript_content,
        )
        self.repository.insert_staged(record)
        if not from_processing:
            # Primero registramos la adopcion; despues movemos para que recovery siga siendo reentrante.
            os.replace(path, processing)
        self.repository.mark_pending(capture_id, processing)
        self._retire_source(source, digest)

    def _find_inbox_by_hash(self, digest: str) -> Path | None:
        for candidate in self.paths.inbox.glob("*.md"):
            try:
                if hashlib.sha256(candidate.read_bytes()).hexdigest() == digest:
                    return candidate
            except OSError:
                continue
        return None

    @staticmethod
    def _verify(path: Path, record: CaptureRecord) -> None:
        RecoveryService._verify_bytes(path.read_bytes(), record)

    @staticmethod
    def _verify_bytes(content: bytes, record: CaptureRecord) -> None:
        if hashlib.sha256(content).hexdigest() != record.sha256:
            raise ValueError("El hash no coincide con el registro SQLite")
        document = parse_capture_bytes(content)
        if document.capture_id != record.capture_id:
            raise ValueError("El capture_id del fichero no coincide con SQLite")

    @staticmethod
    def _retire_source(source: Path | None, digest: str) -> None:
        if not source or not source.exists():
            return
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError("El fichero de inbox cambió; no se elimina")
        source.unlink()

    def _quarantine_orphan(self, path: Path, code: str, message: str) -> None:
        self.quarantine.quarantine(
            path,
            self.paths.failed_contracts,
            {"code": code, "reason": message},
        )
