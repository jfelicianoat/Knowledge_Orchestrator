from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.repositories.capture_repository import CaptureRepository

from .filesystem import atomic_write_json, unique_destination

Checkpoint = Callable[[str], None]


class QuarantineService:
    """Movimiento recuperable de un fichero rechazado y su sidecar."""

    def __init__(
        self,
        paths: PipelinePaths,
        repository: CaptureRepository,
        *,
        checkpoint: Checkpoint | None = None,
    ) -> None:
        self.paths = paths
        self.repository = repository
        self.checkpoint = checkpoint or (lambda _point: None)

    def quarantine(
        self,
        source: Path,
        directory: Path,
        payload: Mapping[str, Any],
        discriminator: str | None = None,
    ) -> Path:
        source = Path(source)
        destination = unique_destination(directory, source.name, discriminator)
        sidecar = destination.with_suffix(destination.suffix + ".error.json")
        intent = directory / f".quarantine-{uuid.uuid4().hex}.pending.json"
        intent_payload = {
            "source_path": str(source.resolve()),
            "destination_path": str(destination.resolve()),
            "sidecar_path": str(sidecar.resolve()),
            "error": {**payload, "source_file": destination.name},
        }
        atomic_write_json(intent, intent_payload)
        self.checkpoint("AFTER_QUARANTINE_INTENT")
        self._complete_intent(intent, intent_payload)
        return destination

    def recover_pending(self) -> int:
        recovered = 0
        for intent in sorted(self.paths.failed.rglob(".quarantine-*.pending.json")):
            try:
                payload = json.loads(intent.read_text(encoding="utf-8"))
                self._complete_intent(intent, payload)
                recovered += 1
            except Exception as error:
                self.repository.record_event(
                    "QUARANTINE_RECOVERY_FAILED",
                    str(error),
                    details={"intent_path": str(intent)},
                )
        return recovered

    def _complete_intent(self, intent: Path, intent_payload: dict[str, Any]) -> None:
        source = Path(intent_payload["source_path"])
        destination = Path(intent_payload["destination_path"])
        sidecar = Path(intent_payload["sidecar_path"])
        error_payload = dict(intent_payload["error"])
        self._validate_managed_paths(source, destination, sidecar, intent)

        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            if not source.exists():
                raise FileNotFoundError("No existe ni el origen ni el destino de la cuarentena")
            os.replace(source, destination)
        self.checkpoint("AFTER_QUARANTINE_MOVE")
        if not sidecar.exists():
            atomic_write_json(sidecar, error_payload)
        self.checkpoint("AFTER_QUARANTINE_SIDECAR")
        intent.unlink(missing_ok=True)
        self.repository.record_event(
            str(error_payload.get("code", "INGESTION_REJECTED")),
            str(error_payload.get("reason", "Fichero rechazado")),
            details={"path": str(destination), **error_payload},
        )

    def _validate_managed_paths(
        self,
        source: Path,
        destination: Path,
        sidecar: Path,
        intent: Path,
    ) -> None:
        source_roots = (self.paths.inbox, self.paths.staging, self.paths.processing)
        if not any(source.resolve().is_relative_to(root.resolve()) for root in source_roots):
            raise ValueError("El origen de cuarentena está fuera de las rutas gestionadas")
        failed_root = self.paths.failed.resolve()
        for path in (destination, sidecar, intent):
            if not path.resolve().is_relative_to(failed_root):
                raise ValueError("La cuarentena debe permanecer dentro de failed")
