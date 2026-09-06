"""Comprobaciones independientes del Broker y del hilo Tk, con concurrencia acotada."""
from __future__ import annotations

import logging
import threading
import time

from knowledge_orchestrator.services.source_monitoring import SourceMonitoringService

logger = logging.getLogger(__name__)


class SourceWorker:
    def __init__(self, service: SourceMonitoringService):
        self.service = service
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._checks: list[threading.Thread] = []

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='source-scheduler', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _check(self, job: dict) -> None:
        try:
            self.service.check(job)
        except Exception:
            # Durable lease recovers after DB failure. Exception text may include remote data.
            logger.error('SOURCE_CHECK_PERSISTENCE_ERROR')

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.service.deliver_ready()
                self.service.ingestion.deliver_pending()
            except Exception:
                logger.error('SOURCE_DELIVERY_ERROR')
            try:
                self._checks = [thread for thread in self._checks if thread.is_alive()]
                jobs = self.service.repository.lease_due(now=time.time(), limit=4 - len(self._checks))
                for job in jobs:
                    if self._stop.is_set():
                        break
                    thread = threading.Thread(target=self._check, args=(job,), name='source-check', daemon=True)
                    self._checks.append(thread)
                    thread.start()
            except Exception:
                logger.error('SOURCE_SCHEDULER_ERROR')
            self._stop.wait(1)
