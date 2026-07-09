from __future__ import annotations

import time
from dataclasses import dataclass

from knowledge_orchestrator.config import BrokerSettings, PipelinePaths
from knowledge_orchestrator.integrations.broker_client import BrokerClient
from knowledge_orchestrator.repositories.capture_repository import CaptureRepository
from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.repositories.domain_repository import DomainRepository
from knowledge_orchestrator.repositories.workflow_repository import WorkflowRepository
from knowledge_orchestrator.repositories.publication_repository import PublicationRepository
from knowledge_orchestrator.repositories.semantic_repository import SemanticRepository
from knowledge_orchestrator.services.broker_dispatch import BrokerDispatcher, BrokerPoller
from knowledge_orchestrator.services.classification import TopicClassifier
from knowledge_orchestrator.services.domain_enrichment import DomainEnrichmentService
from knowledge_orchestrator.services.ingestion import IngestionService
from knowledge_orchestrator.services.model_discovery import ModelDiscoveryService
from knowledge_orchestrator.services.operations import configure_logging
from knowledge_orchestrator.services.publication import PublicationService
from knowledge_orchestrator.services.profile_service import ProfileService
from knowledge_orchestrator.services.recovery import RecoveryReport, RecoveryService
from knowledge_orchestrator.services.semantic_maintenance import SemanticMaintenanceService
from knowledge_orchestrator.services.semantic_broker import SemanticBrokerProcessor
from knowledge_orchestrator.services.topic_service import TopicService
from knowledge_orchestrator.services.workflow_planner import WorkflowPlanner
from knowledge_orchestrator.ui.event_bridge import UiEventBridge
from knowledge_orchestrator.worker.inbox_watcher import InboxWatcher
from knowledge_orchestrator.worker.ingestion_worker import IngestionWorker
from knowledge_orchestrator.worker.broker_worker import BrokerWorker


@dataclass(slots=True)
class OrchestratorRuntime:
    """Agrupa los servicios vivos del Orchestrator y marca el orden de arranque.

    Ojo con cambiar esta coreografia sin revisar recuperacion:
    - Primero se recompone SQLite/filesystem.
    - Luego se reabren publicaciones y jobs semanticos pendientes.
    - Solo al final arrancan watcher y worker Broker, cuando el estado ya esta cuadrado.
    """

    paths: PipelinePaths
    database: Database
    repository: CaptureRepository
    domain_repository: DomainRepository
    workflow_repository: WorkflowRepository
    publication_repository: PublicationRepository
    semantic_repository: SemanticRepository
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
    publication: PublicationService
    semantic_maintenance: SemanticMaintenanceService
    semantic_broker: SemanticBrokerProcessor

    def recover_once(self, *, ingest_inbox: bool = True) -> RecoveryReport:
        """Deja el sistema en un estado reanudable antes de meter trabajo nuevo."""

        report = self.recovery.recover(ingest_inbox=ingest_inbox)
        self.topics.ensure_all_folders()
        self.domain_enrichment.enrich_unassigned_pending()
        self.workflow_repository.recover_interrupted_submissions()
        self.workflow_repository.upgrade_legacy_ready_requests()
        self.publication.recover()
        self.semantic_maintenance.recover()
        for note in self.publication_repository.list_notes_by_status("PUBLISHED"):
            self.semantic_maintenance.schedule_extraction(note.note_id)
        self.workflow_planner.plan_unplanned()
        for workflow_id in self.workflow_repository.list_resumable_workflow_ids():
            self.workflow_planner.advance_workflow(workflow_id)
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
    enable_logging: bool = False,
) -> OrchestratorRuntime:
    """Construye el grafo de dependencias sin arrancar hilos todavia."""

    pipeline_paths = paths or PipelinePaths.defaults()
    pipeline_paths.ensure_directories()
    if enable_logging:
        configure_logging(pipeline_paths)
    database = Database(pipeline_paths.database)
    database.initialize()
    repository = CaptureRepository(database)
    domain_repository = DomainRepository(database)
    workflow_repository = WorkflowRepository(database)
    publication_repository = PublicationRepository(database)
    semantic_repository = SemanticRepository(database)
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
    semantic_maintenance = SemanticMaintenanceService(semantic_repository)
    publication = PublicationService(
        pipeline_paths,
        repository,
        domain_repository,
        publication_repository,
        workflow_planner,
        on_published=lambda note: semantic_maintenance.schedule_extraction(note.note_id),
    )
    semantic_broker = SemanticBrokerProcessor(
        semantic_repository,
        semantic_maintenance,
        broker_client,
        backoff_seconds=settings.submission_backoff_seconds,
    )
    broker_worker = BrokerWorker(
        workflow_planner,
        dispatcher,
        poller,
        discovery,
        bridge.queue,
        settings,
        publication,
        semantic_processor=semantic_broker,
    )
    return OrchestratorRuntime(
        paths=pipeline_paths,
        database=database,
        repository=repository,
        domain_repository=domain_repository,
        workflow_repository=workflow_repository,
        publication_repository=publication_repository,
        semantic_repository=semantic_repository,
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
        publication=publication,
        semantic_maintenance=semantic_maintenance,
        semantic_broker=semantic_broker,
    )
