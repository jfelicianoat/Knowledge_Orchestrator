from __future__ import annotations

import time
from dataclasses import dataclass

from knowledge_orchestrator.config import BrokerSettings, PipelinePaths
from knowledge_orchestrator.integrations.broker_client import BrokerClient
from knowledge_orchestrator.repositories.capture_repository import CaptureRepository
from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.repositories.domain_repository import DomainRepository
from knowledge_orchestrator.repositories.workflow_repository import WorkflowRepository
from knowledge_orchestrator.services.broker_dispatch import BrokerDispatcher, BrokerPoller
from knowledge_orchestrator.services.classification import TopicClassifier
from knowledge_orchestrator.services.domain_enrichment import DomainEnrichmentService
from knowledge_orchestrator.services.ingestion import IngestionService
from knowledge_orchestrator.services.model_discovery import ModelDiscoveryService
from knowledge_orchestrator.services.profile_service import ProfileService
from knowledge_orchestrator.services.recovery import RecoveryReport, RecoveryService
from knowledge_orchestrator.services.topic_service import TopicService
from knowledge_orchestrator.services.workflow_planner import WorkflowPlanner
from knowledge_orchestrator.ui.event_bridge import UiEventBridge
from knowledge_orchestrator.worker.inbox_watcher import InboxWatcher
from knowledge_orchestrator.worker.ingestion_worker import IngestionWorker
from knowledge_orchestrator.worker.broker_worker import BrokerWorker


@dataclass(slots=True)
class OrchestratorRuntime:
    paths: PipelinePaths
    database: Database
    repository: CaptureRepository
    domain_repository: DomainRepository
    workflow_repository: WorkflowRepository
    profiles: ProfileService
    topics: TopicService
    domain_enrichment: DomainEnrichmentService
    ingestion: IngestionService
    recovery: RecoveryService
    bridge: UiEventBridge
    worker: IngestionWorker
    watcher: InboxWatcher
    workflow_planner: WorkflowPlanner
    broker_worker: BrokerWorker

    def recover_once(self, *, ingest_inbox: bool = True) -> RecoveryReport:
        report = self.recovery.recover(ingest_inbox=ingest_inbox)
        self.topics.ensure_all_folders()
        self.domain_enrichment.enrich_unassigned_pending()
        self.workflow_repository.recover_interrupted_submissions()
        self.workflow_planner.plan_unplanned()
        return report

    def start(self) -> RecoveryReport:
        report = self.recover_once(ingest_inbox=True)
        self.watcher.start()
        self.broker_worker.start()
        return report

    def stop(self) -> None:
        self.broker_worker.stop()
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
    broker_settings: BrokerSettings | None = None,
) -> OrchestratorRuntime:
    pipeline_paths = paths or PipelinePaths.defaults()
    pipeline_paths.ensure_directories()
    database = Database(pipeline_paths.database)
    database.initialize()
    repository = CaptureRepository(database)
    domain_repository = DomainRepository(database)
    workflow_repository = WorkflowRepository(database)
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
    settings = broker_settings or BrokerSettings()
    broker_client = BrokerClient(settings)
    workflow_planner = WorkflowPlanner(
        repository,
        domain_repository,
        workflow_repository,
        max_context_tokens=settings.max_context_tokens,
    )
    dispatcher = BrokerDispatcher(
        workflow_repository,
        broker_client,
        backoff_seconds=settings.submission_backoff_seconds,
    )
    poller = BrokerPoller(workflow_repository, broker_client, workflow_planner)
    discovery = ModelDiscoveryService(workflow_repository, broker_client)
    broker_worker = BrokerWorker(
        workflow_planner,
        dispatcher,
        poller,
        discovery,
        bridge.queue,
        settings,
    )
    return OrchestratorRuntime(
        paths=pipeline_paths,
        database=database,
        repository=repository,
        domain_repository=domain_repository,
        workflow_repository=workflow_repository,
        profiles=profiles,
        topics=topics,
        domain_enrichment=domain_enrichment,
        ingestion=ingestion,
        recovery=recovery,
        bridge=bridge,
        worker=worker,
        watcher=watcher,
        workflow_planner=workflow_planner,
        broker_worker=broker_worker,
    )
