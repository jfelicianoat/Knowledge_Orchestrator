from __future__ import annotations

import time
from dataclasses import dataclass

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.repositories.capture_repository import CaptureRepository
from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.services.ingestion import IngestionService
from knowledge_orchestrator.services.recovery import RecoveryReport, RecoveryService
from knowledge_orchestrator.ui.event_bridge import UiEventBridge
from knowledge_orchestrator.worker.inbox_watcher import InboxWatcher
from knowledge_orchestrator.worker.ingestion_worker import IngestionWorker


@dataclass(slots=True)
class OrchestratorRuntime:
    paths: PipelinePaths
    database: Database
    repository: CaptureRepository
    ingestion: IngestionService
    recovery: RecoveryService
    bridge: UiEventBridge
    worker: IngestionWorker
    watcher: InboxWatcher

    def recover_once(self, *, ingest_inbox: bool = True) -> RecoveryReport:
        return self.recovery.recover(ingest_inbox=ingest_inbox)

    def start(self) -> RecoveryReport:
        report = self.recover_once(ingest_inbox=True)
        self.watcher.start()
        return report

    def stop(self) -> None:
        self.watcher.stop()

    def run_forever(self) -> None:
        report = self.start()
        print(f"Recuperación inicial: {report}")
        print(f"Vigilando inbox: {self.paths.inbox}. Pulsa Ctrl+C para detener.")
        try:
            while True:
                for event in self.bridge.drain():
                    print(f"[{event.event_type}] {event.message}")
                time.sleep(0.25)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()


def build_runtime(
    paths: PipelinePaths | None = None,
    *,
    scan_interval_seconds: float = 5.0,
) -> OrchestratorRuntime:
    pipeline_paths = paths or PipelinePaths.defaults()
    pipeline_paths.ensure_directories()
    database = Database(pipeline_paths.database)
    database.initialize()
    repository = CaptureRepository(database)
    ingestion = IngestionService(pipeline_paths, repository)
    recovery = RecoveryService(pipeline_paths, repository, ingestion_service=ingestion)
    bridge = UiEventBridge()
    worker = IngestionWorker(ingestion, bridge.queue)
    watcher = InboxWatcher(
        pipeline_paths,
        worker,
        scan_interval_seconds=scan_interval_seconds,
    )
    return OrchestratorRuntime(
        paths=pipeline_paths,
        database=database,
        repository=repository,
        ingestion=ingestion,
        recovery=recovery,
        bridge=bridge,
        worker=worker,
        watcher=watcher,
    )
