"""Copia integral periódica a una carpeta elegida (p. ej. la nube), con rotación."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.services.operations import create_full_backup

logger = logging.getLogger(__name__)

PREFIX = "knowledge-orchestrator-full-"


class BackupWorker:
    """La base vive en disco local; la copia restaurable viaja a `target`.

    SQLite falla en carpetas sincronizadas («disk I/O error»), pero un ZIP que
    se escribe de una vez sí se puede dejar en Google Drive.
    """

    def __init__(
        self, database: Database, paths: PipelinePaths, target: Path, *,
        interval_seconds: float = 6 * 3600, keep: int = 10, check_seconds: float = 60,
    ) -> None:
        self.database = database
        self.paths = paths
        self.target = Path(target)
        self.interval_seconds = interval_seconds
        self.keep = keep
        self.check_seconds = check_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="periodic-backup", daemon=True)
        self._thread.start()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def backups(self) -> list[Path]:
        """Copias de esta rotación, de la más antigua a la más reciente (el nombre lleva la fecha)."""
        if not self.target.is_dir():
            return []
        return sorted(self.target.glob(f"{PREFIX}*.zip"))

    def due(self, now: float | None = None) -> bool:
        existing = self.backups()
        if not existing:
            return True
        return (now if now is not None else time.time()) - existing[-1].stat().st_mtime >= self.interval_seconds

    def run_once(self) -> Path:
        self.target.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        result = create_full_backup(self.database, self.paths, output_path=self.target / f"{PREFIX}{stamp}.zip")
        for old in self.backups()[:-self.keep]:
            old.unlink(missing_ok=True)
        logger.info("PERIODIC_BACKUP_CREATED %s (%s archivos)", result.path.name, result.files)
        return result.path

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if self.due():
                    self.run_once()
            except Exception:
                # La carpeta de la nube puede no estar montada; se reintenta en la siguiente comprobación.
                logger.exception("PERIODIC_BACKUP_FAILED")
            self._stop.wait(self.check_seconds)
