from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from knowledge_orchestrator.ui.event_bridge import UiEventBridge
from knowledge_orchestrator.worker.inbox_watcher import InboxWatcher
from knowledge_orchestrator.worker.ingestion_worker import IngestionWorker
from tests.helpers import runtime, valid_markdown


class _FakeObserver:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def schedule(self, _event_handler, _path: str, *, recursive: bool) -> object:
        if recursive:
            raise AssertionError("El inbox no debe vigilarse recursivamente")
        return object()

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def join(self, _timeout: float | None = None) -> None:
        return None


class _FailingObserver(_FakeObserver):
    def start(self) -> None:
        raise RuntimeError("observer failed")


class InboxWatcherTests(unittest.TestCase):
    def test_watchdog_event_ingests_without_periodic_rescan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _database, repository, ingestion = runtime(Path(temporary))
            bridge = UiEventBridge()
            worker = IngestionWorker(ingestion, bridge.queue)
            watcher = InboxWatcher(paths, worker, scan_interval_seconds=60)
            watcher.start()
            try:
                time.sleep(0.1)
                source = paths.inbox / "watchdog-event.md"
                source.write_bytes(valid_markdown(capture_id="yt_watchdog_001"))
                deadline = time.monotonic() + 3
                while source.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertFalse(source.exists())
                self.assertEqual(repository.get("yt_watchdog_001").status.value, "PENDING")
            finally:
                watcher.stop()

    def test_periodic_rescan_ingests_file_created_after_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _database, repository, ingestion = runtime(Path(temporary))
            bridge = UiEventBridge()
            worker = IngestionWorker(ingestion, bridge.queue)
            observer = _FakeObserver()
            watcher = InboxWatcher(
                paths,
                worker,
                scan_interval_seconds=0.01,
                observer_factory=lambda: observer,
            )
            watcher.start()
            try:
                source = paths.inbox / "created-after-start.md"
                source.write_bytes(valid_markdown())
                deadline = time.monotonic() + 2
                while source.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(repository.count(), 1)
                self.assertFalse(source.exists())
                self.assertTrue(observer.started)
            finally:
                watcher.stop()
            self.assertTrue(observer.stopped)

    def test_repeated_scan_does_not_enqueue_same_path_twice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _database, _repository, ingestion = runtime(Path(temporary))
            source = paths.inbox / "capture.md"
            source.write_bytes(valid_markdown())
            bridge = UiEventBridge()
            worker = IngestionWorker(ingestion, bridge.queue)
            watcher = InboxWatcher(paths, worker, observer_factory=_FakeObserver)
            worker.start()
            try:
                self.assertEqual(watcher.scan_once(), 1)
                self.assertEqual(watcher.scan_once(), 0)
            finally:
                worker.stop()

    def test_observer_start_failure_also_stops_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _database, _repository, ingestion = runtime(Path(temporary))
            bridge = UiEventBridge()
            worker = IngestionWorker(ingestion, bridge.queue)
            watcher = InboxWatcher(paths, worker, observer_factory=_FailingObserver)
            with self.assertRaisesRegex(RuntimeError, "observer failed"):
                watcher.start()
            self.assertFalse(worker._thread and worker._thread.is_alive())


if __name__ == "__main__":
    unittest.main()
