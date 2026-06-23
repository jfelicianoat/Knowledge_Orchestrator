from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.domain.models import TopicDefinition
from knowledge_orchestrator.domain.topics import TopicValidationError
from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.repositories.domain_repository import DomainRepository
from knowledge_orchestrator.services.classification import (
    TopicClassifier,
    calculate_obsolescence_date,
    is_obsolete,
)
from knowledge_orchestrator.services.topic_service import TopicService


class TopicServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.paths = PipelinePaths.under(Path(self.temporary.name))
        self.paths.ensure_directories()
        database = Database(self.paths.database)
        database.initialize()
        self.repository = DomainRepository(database)
        self.service = TopicService(self.paths, self.repository)
        self.profile_id = self.repository.list_profiles(enabled_only=True)[0].profile_id or 0

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def topic(self, name: str, position: int, keywords: tuple[str, ...], **overrides) -> TopicDefinition:
        values = {
            "name": name,
            "folder": name,
            "keywords": keywords,
            "position": position,
            "default_profile_id": self.profile_id,
            "obsolescence_days": 30,
        }
        values.update(overrides)
        return TopicDefinition(**values)

    def test_first_matching_topic_wins_and_fallback_is_inbox(self) -> None:
        broad = self.service.save_topic(self.topic("IA", 20, ("ollama", "llm")))
        preferred = self.service.save_topic(self.topic("Local", 10, ("ollama",)))
        inbox = self.repository.get_inbox_topic()
        classifier = TopicClassifier()
        match = classifier.classify(
            {"title": "Configuración de Ollama", "channel": "Tech"},
            self.service.list_topics(enabled_only=True),
            inbox,
        )
        self.assertEqual(match.topic_id, preferred.topic_id)
        fallback = classifier.classify(
            {"title": "Jardinería doméstica"},
            self.service.list_topics(enabled_only=True),
            inbox,
        )
        self.assertEqual(fallback.name, "_inbox")
        self.assertTrue((self.paths.obsidian_vault / broad.folder).is_dir())

    def test_short_keyword_does_not_match_inside_another_word(self) -> None:
        topic = self.service.save_topic(self.topic("IA", 1, ("ia",)))
        result = TopicClassifier().classify(
            {"title": "Historia contemporánea"},
            self.service.list_topics(enabled_only=True),
            self.repository.get_inbox_topic(),
        )
        self.assertNotEqual(result.topic_id, topic.topic_id)

    def test_reorders_topics_without_moving_reserved_inbox(self) -> None:
        first = self.service.save_topic(self.topic("Primero", 10, ("uno",)))
        second = self.service.save_topic(self.topic("Segundo", 20, ("dos",)))
        self.service.reorder_topics([second.topic_id or 0, first.topic_id or 0])
        ordered = self.service.list_topics()
        self.assertEqual([item.name for item in ordered], ["Segundo", "Primero", "_inbox"])

    def test_validates_folder_and_obsolescence(self) -> None:
        with self.assertRaises(TopicValidationError):
            self.service.save_topic(self.topic("Unsafe", 1, ("x",), folder="../fuera"))
        with self.assertRaises(TopicValidationError):
            self.service.save_topic(self.topic("Reserved", 1, ("x",), folder="CON"))
        topic = self.service.save_topic(self.topic("Vigente", 2, ("vigente",), obsolescence_days=10))
        expires = calculate_obsolescence_date("2026-06-23T10:00:00Z", topic)
        self.assertEqual(expires, date(2026, 7, 3))
        self.assertFalse(is_obsolete(expires, today=date(2026, 7, 2)))
        self.assertTrue(is_obsolete(expires, today=date(2026, 7, 3)))


if __name__ == "__main__":
    unittest.main()
