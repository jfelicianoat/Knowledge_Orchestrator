from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.domain.contracts import parse_capture_bytes
from knowledge_orchestrator.domain.errors import (
    CaptureContractError,
    FileLockedError,
    FileStabilityError,
    IngestionCancelled,
)
from knowledge_orchestrator.domain.models import CaptureRecord, CaptureStatus, IngestionResult
from knowledge_orchestrator.repositories.capture_repository import CaptureRepository

from .file_stability import FileStabilityChecker, read_bytes_with_lock_retries
from .filesystem import unique_destination, write_synced
from .quarantine import QuarantineService

Checkpoint = Callable[[str], None]


class IngestionService:
    """Gestiona la ingesta durable de capturas desde inbox.

    Ojo con esto:
    - SQLite y NTFS no comparten transaccion, asi que el orden de pasos es parte del contrato.
    - Primero validamos y sincronizamos la copia; despues persistimos; solo entonces movemos.
    - Si el proceso cae a mitad, RecoveryService tiene que poder seguir la jugada sin duplicar.
    """

    def __init__(
        self,
        paths: PipelinePaths,
        repository: CaptureRepository,
        *,
        stability_checker: FileStabilityChecker | None = None,
        checkpoint: Checkpoint | None = None,
        read_file: Callable[[Path], bytes] | None = None,
        on_accepted: Callable[[str], object] | None = None,
    ) -> None:
        self.paths = paths
        self.repository = repository
        self.stability_checker = stability_checker or FileStabilityChecker()
        self.checkpoint = checkpoint or (lambda _point: None)
        self._cancel_event = threading.Event()
        self.read_file = read_file or (
            lambda path: read_bytes_with_lock_retries(path, cancel_event=self._cancel_event)
        )
        self.quarantine = QuarantineService(paths, repository, checkpoint=self.checkpoint)
        self.on_accepted = on_accepted

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def clear_cancel(self) -> None:
        self._cancel_event.clear()

    def ingest(self, source_path: Path) -> IngestionResult:
        """Acepta un Markdown del inbox o lo manda a cuarentena con causa trazable."""

        source = Path(source_path)
        self.paths.ensure_directories()
        if source.suffix.lower() != ".md":
            return IngestionResult(False, None, None, "UNSUPPORTED_FILE", "Solo se admiten ficheros .md")
        if source.resolve().parent != self.paths.inbox.resolve():
            raise ValueError("La ingesta solo acepta ficheros ubicados directamente en inbox")

        try:
            self.stability_checker.wait_until_stable(source, cancel_event=self._cancel_event)
            original_bytes = self.read_file(source)
        except IngestionCancelled as error:
            self.repository.record_event("INGESTION_CANCELLED", str(error), details={"path": str(source)})
            return IngestionResult(False, None, None, "INGESTION_CANCELLED", str(error))
        except FileLockedError as error:
            self.repository.record_event("FILE_LOCKED", str(error), details={"path": str(source)})
            return IngestionResult(False, None, None, "FILE_LOCKED", str(error))
        except FileStabilityError as error:
            self.repository.record_event("FILE_UNSTABLE", str(error), details={"path": str(source)})
            return IngestionResult(False, None, None, "FILE_UNSTABLE", str(error))

        # Esta es la frontera plugin -> Orchestrator: nada toca staging ni SQLite
        # hasta que el contrato local este validado.
        try:
            document = parse_capture_bytes(original_bytes)
        except CaptureContractError as error:
            self._reject(source, self.paths.failed_contracts, error.issue.as_dict())
            return IngestionResult(False, None, None, error.issue.code, str(error))

        capture_id = document.capture_id
        if not bool(document.metadata["has_transcript"]):
            payload = {
                "code": "TRANSCRIPTION_MISSING",
                "boundary": "plugin_to_orchestrator",
                "field": "transcript_content",
                "reason": "La fuente no contiene transcripción",
                "contract_version": document.contract_version,
                "capture_id": capture_id,
            }
            self._reject(source, self.paths.failed_transcriptions, payload, capture_id)
            return IngestionResult(False, capture_id, None, "TRANSCRIPTION_MISSING", payload["reason"])

        if self.repository.get(capture_id) is not None:
            payload = {
                "code": "DUPLICATE_CAPTURE",
                "capture_id": capture_id,
                "reason": "capture_id ya registrado",
            }
            self._reject(source, self.paths.failed_duplicates, payload, capture_id)
            return IngestionResult(False, capture_id, None, "DUPLICATE_CAPTURE", payload["reason"])

        digest = hashlib.sha256(original_bytes).hexdigest()
        staging_path = self.paths.staging / f"{capture_id}.part"
        processing_path = unique_destination(self.paths.processing, source.name, capture_id)
        if staging_path.exists() and hashlib.sha256(staging_path.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Staging conflictivo para {capture_id}")
        if not staging_path.exists():
            write_synced(staging_path, original_bytes)
        staged_bytes = staging_path.read_bytes()
        if hashlib.sha256(staged_bytes).hexdigest() != digest:
            raise RuntimeError(f"Hash distinto después de copiar {capture_id} a staging")
        staged_document = parse_capture_bytes(staged_bytes)
        if staged_document.capture_id != capture_id:
            raise RuntimeError("capture_id cambió al revalidar staging")
        # Este checkpoint no es decorativo; permite a los tests simular una caida justo aqui.
        self.checkpoint("AFTER_STAGING_SYNC")

        record = CaptureRecord(
            capture_id=capture_id,
            contract_version=document.contract_version,
            source_type=document.source_type,
            title=document.title,
            status=CaptureStatus.STAGED,
            source_path=source,
            staging_path=staging_path,
            processing_path=processing_path,
            sha256=digest,
            original_filename=source.name,
            metadata_json=json.dumps(dict(document.metadata), ensure_ascii=False, sort_keys=True, default=str),
            transcript_content=document.transcript_content,
        )
        self.repository.insert_staged(record)
        # A partir de aqui recovery ya sabe que la captura existe aunque el proceso caiga.
        self.checkpoint("AFTER_STAGED_COMMIT")

        # Aqui no movemos el fichero "a lo loco": SQLite ya tiene staging, hash y destino.
        # Si la app se cae despues del replace, RecoveryService puede rematar el estado.
        os.replace(staging_path, processing_path)
        self.checkpoint("AFTER_PROCESSING_MOVE")
        self.repository.mark_pending(capture_id, processing_path)
        self.checkpoint("AFTER_PENDING_COMMIT")
        if source.exists():
            current_digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if current_digest != digest:
                self.repository.record_event(
                    "SOURCE_CHANGED_AFTER_STAGING",
                    "El original cambió después del commit y se conserva en inbox",
                    capture_id=capture_id,
                    details={"path": str(source), "expected_sha256": digest, "actual_sha256": current_digest},
                )
                raise RuntimeError("El original cambió después del staging; no se elimina")
            source.unlink()
        self.checkpoint("AFTER_SOURCE_REMOVAL")
        if self.on_accepted is not None:
            try:
                self.on_accepted(capture_id)
            except Exception as error:
                self.repository.record_event(
                    "DOMAIN_ENRICHMENT_FAILED",
                    str(error),
                    capture_id=capture_id,
                    details={"capture_id": capture_id},
                )
        return IngestionResult(True, capture_id, CaptureStatus.PENDING)

    def _reject(
        self,
        source: Path,
        directory: Path,
        payload: dict[str, object],
        discriminator: str | None = None,
    ) -> None:
        self.quarantine.quarantine(source, directory, payload, discriminator)
