from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.domain.models import SourceOrigin, TopicDefinition
from knowledge_orchestrator.domain.sources import autonomous_sources_enabled
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.file_stability import FileStabilityChecker
from tests.helpers import generic_markdown, valid_markdown
from tests.helpers import runtime as phase_one_runtime


class DomainEnrichmentTests(unittest.TestCase):
    def test_generic_user_file_is_classified_and_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = PipelinePaths.under(Path(temporary))
            runtime = build_runtime(paths)
            runtime.ingestion.stability_checker = FileStabilityChecker(
                interval_seconds=0,
                sleep=lambda _seconds: None,
            )
            profile = runtime.profiles.list_profiles(enabled_only=True)[0]
            topic = runtime.topics.save_topic(TopicDefinition(
                name="Desarrollo",
                folder="Desarrollo/Python",
                keywords=("python", "programación"),
                position=1,
                default_profile_id=profile.profile_id or 0,
                obsolescence_days=365,
            ))
            source = paths.inbox / "manual.md"
            source.write_bytes(generic_markdown())
            result = runtime.ingestion.ingest(source)
            self.assertTrue(result.accepted)
            record = runtime.repository.get(result.capture_id or "")
            self.assertEqual(record.topic_id, topic.topic_id)
            self.assertEqual(record.profile_id, profile.profile_id)
            self.assertEqual(record.source_origin, SourceOrigin.USER_FILE)
            self.assertEqual(record.obsolescence_date, "2027-06-23")
            self.assertIsNotNone(record.domain_enriched_at)
            self.assertTrue((paths.obsidian_vault / "Desarrollo" / "Python").is_dir())

    def test_mvp_has_no_autonomous_source_producers(self) -> None:
        self.assertFalse(autonomous_sources_enabled())

    def test_plugin_capture_falls_back_to_inbox_with_plugin_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = PipelinePaths.under(Path(temporary))
            runtime = build_runtime(paths)
            runtime.ingestion.stability_checker = FileStabilityChecker(interval_seconds=0, sleep=lambda _seconds: None)
            source = paths.inbox / "youtube.md"
            source.write_bytes(valid_markdown())
            result = runtime.ingestion.ingest(source)
            record = runtime.repository.get(result.capture_id or "")
            inbox = runtime.domain_repository.get_inbox_topic()
            self.assertEqual(record.topic_id, inbox.topic_id)
            self.assertEqual(record.source_origin, SourceOrigin.PLUGIN_CAPTURE)
            self.assertIsNone(record.obsolescence_date)

    def test_startup_enriches_pending_capture_created_before_phase_two(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _database, repository, ingestion = phase_one_runtime(Path(temporary))
            source = paths.inbox / "legacy.md"
            source.write_bytes(generic_markdown(capture_id="legacy_document"))
            result = ingestion.ingest(source)
            self.assertIsNone(repository.get(result.capture_id or "").domain_enriched_at)

            upgraded = build_runtime(paths)
            upgraded.recover_once(ingest_inbox=False)
            record = upgraded.repository.get("legacy_document")
            self.assertIsNotNone(record.domain_enriched_at)
            self.assertEqual(record.topic_id, upgraded.domain_repository.get_inbox_topic().topic_id)


if __name__ == "__main__":
    unittest.main()
