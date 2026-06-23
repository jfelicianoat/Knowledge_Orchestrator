from __future__ import annotations

import json

from knowledge_orchestrator.domain.models import CaptureDocument, CaptureStatus, TopicAssignment
from knowledge_orchestrator.domain.sources import infer_source_origin
from knowledge_orchestrator.repositories.capture_repository import CaptureRepository
from knowledge_orchestrator.repositories.domain_repository import DomainRepository

from .classification import TopicClassifier, calculate_obsolescence_date
from .profile_service import ProfileService
from .topic_service import TopicService


class DomainEnrichmentService:
    def __init__(
        self,
        captures: CaptureRepository,
        domains: DomainRepository,
        topics: TopicService,
        profiles: ProfileService,
        classifier: TopicClassifier | None = None,
    ) -> None:
        self.captures = captures
        self.domains = domains
        self.topics = topics
        self.profiles = profiles
        self.classifier = classifier or TopicClassifier()

    def enrich_capture(self, capture_id: str) -> TopicAssignment:
        record = self.captures.get(capture_id)
        if record is None:
            raise ValueError(f"Captura inexistente: {capture_id}")
        if record.status is not CaptureStatus.PENDING:
            raise ValueError("Solo se enriquecen capturas PENDING")
        if record.domain_enriched_at is not None:
            raise ValueError("La captura ya fue enriquecida")
        metadata = json.loads(record.metadata_json)
        if not isinstance(metadata, dict):
            raise ValueError("metadata_json no contiene un objeto")
        document = CaptureDocument(
            metadata=metadata,
            transcript_content=record.transcript_content,
            raw_markdown="",
        )
        inbox = self.domains.get_inbox_topic()
        topic = self.classifier.classify(metadata, self.topics.list_topics(enabled_only=True), inbox)
        profile = self.profiles.get_profile(topic.default_profile_id)
        if not profile.enabled:
            raise ValueError(f"El perfil {profile.name} está deshabilitado")
        self.topics.ensure_folder(topic)
        origin = infer_source_origin(document)
        obsolescence = calculate_obsolescence_date(str(metadata["captured_at"]), topic)
        self.domains.assign_capture(
            capture_id,
            topic_id=topic.topic_id or 0,
            profile_id=profile.profile_id or 0,
            source_origin=origin,
            obsolescence_date=obsolescence,
        )
        return TopicAssignment(
            capture_id=capture_id,
            topic_id=topic.topic_id or 0,
            topic_name=topic.name,
            folder=topic.folder,
            profile_id=profile.profile_id or 0,
            source_origin=origin,
            obsolescence_date=obsolescence.isoformat() if obsolescence else None,
        )

    def enrich_unassigned_pending(self) -> list[TopicAssignment]:
        assignments: list[TopicAssignment] = []
        for record in self.captures.list_unenriched_pending():
            try:
                assignments.append(self.enrich_capture(record.capture_id))
            except Exception as error:
                self.captures.record_event(
                    "DOMAIN_ENRICHMENT_FAILED",
                    str(error),
                    capture_id=record.capture_id,
                    details={"capture_id": record.capture_id},
                )
        return assignments
