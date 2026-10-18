"""Copia al log de aplicación lo que pasa en el pipeline (auditoría 14-oct OBS-LOG).

`orchestrator.log` solo tenía tráfico HTTP: ingesta, cuarentena, reintentos,
publicación o cancelación quedaban únicamente en la tabla `events`, que escriben
una veintena de repositorios. En vez de tocarlos todos, este hilo lee los
eventos nuevos y los registra a nivel INFO (sin `details_json`, que puede llevar
contenido).
"""
from __future__ import annotations

import logging
import threading
from contextlib import closing

from knowledge_orchestrator.repositories.database import Database

logger = logging.getLogger("knowledge_orchestrator.events")


class EventLogWorker:
    def __init__(self, database: Database, *, interval_seconds: float = 2.0) -> None:
        self.database = database
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Lo anterior a esta sesión ya está en el log de su sesión; lo de la recuperación al arrancar, no.
        self._last_id = self._max_event_id()

    def _max_event_id(self) -> int:
        with closing(self.database.connect(readonly=True)) as connection:
            return int(connection.execute("SELECT COALESCE(MAX(event_id), 0) FROM events").fetchone()[0])

    def flush(self) -> int:
        """Registra los eventos nuevos; devuelve cuántos."""

        with closing(self.database.connect(readonly=True)) as connection:
            rows = connection.execute(
                "SELECT event_id, event_type, capture_id, message FROM events WHERE event_id > ? "
                "ORDER BY event_id LIMIT 500",
                (self._last_id,),
            ).fetchall()
        for row in rows:
            logger.info("%s capture=%s %s", row["event_type"], row["capture_id"] or "-", row["message"] or "")
            self._last_id = int(row["event_id"])
        return len(rows)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="event-log", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        try:
            self.flush()
        except Exception:
            logger.error("EVENT_LOG_FLUSH_ERROR")

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.flush()
            except Exception:
                logger.error("EVENT_LOG_FLUSH_ERROR")
