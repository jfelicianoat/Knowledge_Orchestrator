from __future__ import annotations

import queue
import threading
import tempfile
import time
import unittest
from pathlib import Path

from knowledge_orchestrator.domain.models import CaptureStatus, IngestionResult
from knowledge_orchestrator.ui.event_bridge import UiEventBridge
from knowledge_orchestrator.worker.ingestion_worker import IngestionWorker
from knowledge_orchestrator.services.file_stability import FileStabilityChecker
from knowledge_orchestrator.services.ingestion import IngestionService

from tests.helpers import runtime, valid_markdown


class _FakeIngestionService:
    def ingest(self, _path: Path) -> IngestionResult:
        return IngestionResult(True, "capture_001", CaptureStatus.PENDING)


class _LockedIngestionService:
    def __init__(self) -> None:
        self.calls = 0

    def ingest(self, _path: Path) -> IngestionResult:
        self.calls += 1
        return IngestionResult(False, None, None, "FILE_LOCKED", "locked")


class WorkerUiBoundaryTests(unittest.TestCase):
    def test_worker_publishes_immutable_event_without_touching_ui(self) -> None:
        bridge = UiEventBridge()
        worker = IngestionWorker(_FakeIngestionService(), bridge.queue)  # type: ignore[arg-type]
        worker.start()
        worker.submit(Path("capture.md"))
        event = bridge.queue.get(timeout=2)
        worker.stop()
        self.assertEqual(event.event_type, "INGESTION_RESULT")
        self.assertEqual(event.capture_id, "capture_001")
        self.assertTrue(event.details["accepted"])

    def test_ui_events_can_only_be_drained_on_main_thread(self) -> None:
        bridge = UiEventBridge()
        errors: "queue.Queue[Exception]" = queue.Queue()

        def consume() -> None:
            try:
                bridge.drain()
            except Exception as error:
                errors.put(error)

        thread = threading.Thread(target=consume)
        thread.start()
        thread.join()
        self.assertIsInstance(errors.get_nowait(), RuntimeError)

    def test_stop_cancels_long_stability_wait_without_deleting_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _database, repository, _ingestion = runtime(Path(temporary))
            service = IngestionService(
                paths,
                repository,
                stability_checker=FileStabilityChecker(interval_seconds=30),
            )
            bridge = UiEventBridge()
            worker = IngestionWorker(service, bridge.queue)
            source = paths.inbox / "slow.md"
            source.write_bytes(valid_markdown())
            worker.start()
            worker.submit(source)
            time.sleep(0.05)
            started = time.monotonic()
            worker.stop(timeout=1)
            self.assertLess(time.monotonic() - started, 1)
            event = bridge.queue.get(timeout=1)
            self.assertEqual(event.details["error_code"], "INGESTION_CANCELLED")
            self.assertTrue(source.exists())
            self.assertEqual(repository.count(), 0)

    def test_locked_file_requires_explicit_retry_while_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "locked.md"
            path.write_text("locked", encoding="utf-8")
            bridge = UiEventBridge()
            service = _LockedIngestionService()
            worker = IngestionWorker(service, bridge.queue)  # type: ignore[arg-type]
            worker.start()
            try:
                self.assertTrue(worker.submit(path))
                bridge.queue.get(timeout=1)
                self.assertFalse(worker.submit(path))
                self.assertEqual(service.calls, 1)
                self.assertTrue(worker.retry(path))
                bridge.queue.get(timeout=1)
                self.assertEqual(service.calls, 2)
            finally:
                worker.stop()


if __name__ == "__main__":
    unittest.main()
