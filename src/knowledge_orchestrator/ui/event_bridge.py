from __future__ import annotations

import queue
import threading

from knowledge_orchestrator.domain.models import ApplicationEvent


class UiEventBridge:
    """Cola thread-safe que la futura UI vaciará exclusivamente desde el hilo principal."""

    def __init__(self) -> None:
        self.queue: queue.Queue[ApplicationEvent] = queue.Queue()
        self.main_thread_id = threading.main_thread().ident

    def drain(self, limit: int = 100) -> list[ApplicationEvent]:
        if threading.get_ident() != self.main_thread_id:
            raise RuntimeError("Solo el hilo principal puede consumir eventos de UI")
        events: list[ApplicationEvent] = []
        for _ in range(limit):
            try:
                events.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return events
