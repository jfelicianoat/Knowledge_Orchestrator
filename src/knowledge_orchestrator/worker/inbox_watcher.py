from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from knowledge_orchestrator.config import PipelinePaths

from .ingestion_worker import IngestionWorker


class ObserverLike(Protocol):
    def schedule(self, event_handler: FileSystemEventHandler, path: str, *, recursive: bool) -> object: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def join(self, timeout: float | None = None) -> None: ...


class _InboxEventHandler(FileSystemEventHandler):
    def __init__(self, submit: Callable[[Path], bool]) -> None:
        self.submit = submit

    def on_created(self, event: FileSystemEvent) -> None:
        self._submit_file(event.src_path, event.is_directory)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._submit_file(event.src_path, event.is_directory)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._submit_file(event.dest_path, event.is_directory)

    def _submit_file(self, raw_path: str, is_directory: bool) -> None:
        path = Path(raw_path)
        if not is_directory and path.suffix.lower() == ".md":
            self.submit(path)


class InboxWatcher:
    """Combina eventos watchdog con un rescan periódico para no perder eventos."""

    def __init__(
        self,
        paths: PipelinePaths,
        worker: IngestionWorker,
        *,
        scan_interval_seconds: float = 5.0,
        observer_factory: Callable[[], ObserverLike] = Observer,
    ) -> None:
        self.paths = paths
        self.worker = worker
        self.scan_interval_seconds = scan_interval_seconds
        self.observer_factory = observer_factory
        self._observer: ObserverLike | None = None
        self._scanner: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._observer is not None:
            return
        self.paths.ensure_directories()
        self._stop.clear()
        self.worker.start()
        handler = _InboxEventHandler(self.worker.submit)
        observer = self.observer_factory()
        self._observer = observer
        try:
            observer.schedule(handler, str(self.paths.inbox), recursive=False)
            observer.start()
            self._scanner = threading.Thread(target=self._scan_loop, name="inbox-rescan", daemon=True)
            self._scanner.start()
        except BaseException:
            try:
                observer.stop()
                observer.join(1)
            except Exception:
                pass
            self._observer = None
            self.worker.stop()
            raise

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout)
            self._observer = None
        if self._scanner is not None:
            self._scanner.join(timeout)
            if self._scanner.is_alive():
                raise TimeoutError("El rescan del inbox no se detuvo a tiempo")
            self._scanner = None
        self.worker.stop(timeout)

    def scan_once(self) -> int:
        submitted = 0
        for path in sorted(self.paths.inbox.glob("*.md")):
            submitted += int(self.worker.submit(path))
        return submitted

    def _scan_loop(self) -> None:
        while not self._stop.is_set():
            self.scan_once()
            self._stop.wait(self.scan_interval_seconds)
