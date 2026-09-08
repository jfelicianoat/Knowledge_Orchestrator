"""Worker local de políticas, independiente de disponibilidad y scheduling del Broker."""
from __future__ import annotations

import logging
import threading

from knowledge_orchestrator.services.automation_scheduler import AutomationScheduler

logger = logging.getLogger(__name__)


class AutomationWorker:
    def __init__(self, scheduler: AutomationScheduler) -> None:
        self.scheduler = scheduler
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='automation-policies', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.scheduler.tick()
            except Exception:
                logger.error('AUTOMATION_SCHEDULER_ERROR')
            self._stop.wait(1)
