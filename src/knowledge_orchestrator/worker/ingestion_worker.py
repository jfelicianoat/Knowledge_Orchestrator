from __future__ import annotations

import queue
import threading
from pathlib import Path

from knowledge_orchestrator.domain.models import ApplicationEvent
from knowledge_orchestrator.services.ingestion import IngestionService


class IngestionWorker:
    """Worker serial de filesystem; nunca toca widgets de Tk."""

    def __init__(self, service: IngestionService, events: "queue.Queue[ApplicationEvent]") -> None:
        self.service = service
        self.events = events
        self._requests: "queue.Queue[Path | None]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._pending: set[Path] = set()
        self._suppressed: dict[Path, tuple[int, int] | None] = {}
        self._pending_lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        clear_cancel = getattr(self.service, "clear_cancel", None)
        if clear_cancel:
            clear_cancel()
        self._thread = threading.Thread(target=self._run, name="ingestion-worker", daemon=True)
        self._thread.start()

    def submit(self, path: Path) -> bool:
        normalized = Path(path).resolve()
        with self._pending_lock:
            if normalized in self._pending:
                return False
            if normalized in self._suppressed:
                current = self._fingerprint(normalized)
                if current == self._suppressed[normalized]:
                    return False
                self._suppressed.pop(normalized, None)
            self._pending.add(normalized)
        self._requests.put(normalized)
        return True

    def retry(self, path: Path) -> bool:
        normalized = Path(path).resolve()
        with self._pending_lock:
            self._suppressed.pop(normalized, None)
        return self.submit(normalized)

    def stop(self, timeout: float = 5.0) -> None:
        if self._thread and self._thread.is_alive():
            request_cancel = getattr(self.service, "request_cancel", None)
            if request_cancel:
                request_cancel()
            while True:
                try:
                    pending = self._requests.get_nowait()
                except queue.Empty:
                    break
                if pending is not None:
                    with self._pending_lock:
                        self._pending.discard(pending)
            self._requests.put(None)
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise TimeoutError("El worker de ingesta no se detuvo a tiempo")

    def _run(self) -> None:
        while True:
            path = self._requests.get()
            if path is None:
                return
            try:
                result = self.service.ingest(path)
                if result.error_code in {"FILE_LOCKED", "FILE_UNSTABLE"}:
                    with self._pending_lock:
                        self._suppressed[path] = self._fingerprint(path)
                self.events.put(
                    ApplicationEvent(
                        event_type="INGESTION_RESULT",
                        capture_id=result.capture_id,
                        message=result.message or ("Captura aceptada" if result.accepted else "Captura rechazada"),
                        details={"accepted": result.accepted, "error_code": result.error_code},
                    )
                )
            except Exception as error:
                self.events.put(
                    ApplicationEvent(
                        event_type="INGESTION_CRASH",
                        capture_id=None,
                        message=str(error),
                        details={"path": str(path)},
                    )
                )
            finally:
                with self._pending_lock:
                    self._pending.discard(path)

    @staticmethod
    def _fingerprint(path: Path) -> tuple[int, int] | None:
        try:
            stat = path.stat()
            return stat.st_size, stat.st_mtime_ns
        except FileNotFoundError:
            return None
