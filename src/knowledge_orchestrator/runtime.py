from __future__ import annotations

import time
from dataclasses import dataclass

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.repositories.capture_repository import CaptureRepository
from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.repositories.domain_repository import DomainRepository
from knowledge_orchestrator.services.classification import TopicClassifier
from knowledge_orchestrator.services.domain_enrichment import DomainEnrichmentService
from knowledge_orchestrator.services.ingestion import IngestionService
from knowledge_orchestrator.services.profile_service import ProfileService
from knowledge_orchestrator.services.recovery import RecoveryReport, RecoveryService
from knowledge_orchestrator.services.topic_service import TopicService
from knowledge_orchestrator.ui.event_bridge import UiEventBridge
from knowledge_orchestrator.worker.inbox_watcher import InboxWatcher
from knowledge_orchestrator.worker.ingestion_worker import IngestionWorker


@dataclass(slots=True)
class OrchestratorRuntime:
    paths: PipelinePaths
    database: Database
    repository: CaptureRepository
    domain_repository: DomainRepository
    profiles: ProfileService
    topics: TopicService
    domain_enrichment: DomainEnrichmentService
    ingestion: IngestionService
    recovery: RecoveryService
    bridge: UiEventBridge
    worker: IngestionWorker
    watcher: InboxWatcher

    def recover_once(self, *, ingest_inbox: bool = True) -> RecoveryReport:
        report = self.recovery.recover(ingest_inbox=ingest_inbox)
        self.topics.ensure_all_folders()
        self.domain_enrichment.enrich_unassigned_pending()
        return report

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
    domain_repository = DomainRepository(database)
    profiles = ProfileService(domain_repository)
    topics = TopicService(pipeline_paths, domain_repository)
    domain_enrichment = DomainEnrichmentService(
        repository,
        domain_repository,
        topics,
        profiles,
        TopicClassifier(),
    )
    ingestion = IngestionService(
        pipeline_paths,
        repository,
        on_accepted=domain_enrichment.enrich_capture,
    )
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
        domain_repository=domain_repository,
        profiles=profiles,
        topics=topics,
        domain_enrichment=domain_enrichment,
        ingestion=ingestion,
        recovery=recovery,
        bridge=bridge,
        worker=worker,
        watcher=watcher,
    )
