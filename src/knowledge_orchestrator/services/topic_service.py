from __future__ import annotations

from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.domain.models import TopicDefinition
from knowledge_orchestrator.domain.topics import validate_topic
from knowledge_orchestrator.repositories.domain_repository import DomainRepository


class TopicService:
    def __init__(self, paths: PipelinePaths, repository: DomainRepository) -> None:
        self.paths = paths
        self.repository = repository

    def list_topics(self, *, enabled_only: bool = False) -> list[TopicDefinition]:
        return self.repository.list_topics(enabled_only=enabled_only)

    def save_topic(self, topic: TopicDefinition) -> TopicDefinition:
        validated = validate_topic(topic)
        if validated.name.casefold() == "_inbox" and validated.name != "_inbox":
            raise ValueError("El nombre _inbox está reservado")
        if validated.name == "_inbox" and (
            validated.folder != "_inbox"
            or validated.position != 2_147_483_647
            or validated.keywords
            or validated.is_updatable
        ):
            raise ValueError("El tema reservado _inbox no puede cambiar sus invariantes")
        saved = self.repository.save_topic(validated)
        self.ensure_folder(saved)
        return saved

    def reorder_topics(self, ordered_topic_ids: list[int]) -> None:
        self.repository.reorder_topics(ordered_topic_ids)

    def ensure_folder(self, topic: TopicDefinition) -> Path:
        root = self.paths.obsidian_vault.resolve()
        target = (root / topic.folder).resolve()
        if not target.is_relative_to(root):
            raise ValueError("La carpeta del tema escapa del vault")
        target.mkdir(parents=True, exist_ok=True)
        return target

    def ensure_all_folders(self) -> None:
        for topic in self.list_topics(enabled_only=True):
            self.ensure_folder(topic)
