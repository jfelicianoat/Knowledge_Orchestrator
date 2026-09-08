"""Ejecuta únicamente lotes confirmados, independientemente del Broker."""
from __future__ import annotations

import logging
import threading

from knowledge_orchestrator.services.review_batches import ReviewBatchService

logger = logging.getLogger(__name__)


class ReviewWorker:
    def __init__(self, service: ReviewBatchService) -> None:
        self.service = service
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='review-batches', daemon=True)
        self._thread.start()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.service.run_next()
            except Exception:
                # El recibo durable permite recuperar al arrancar; no registrar contenido.
                logger.error('REVIEW_BATCH_EXECUTION_ERROR')
            self._stop.wait(1)
