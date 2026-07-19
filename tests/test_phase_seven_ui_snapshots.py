from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.file_stability import FileStabilityChecker
from knowledge_orchestrator.ui.dashboard import data_root_label
from knowledge_orchestrator.ui.snapshots import UiSnapshotService
from tests.helpers import generic_markdown


class PhaseSevenUiSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runtime = build_runtime(PipelinePaths.under(self.root))
        self.runtime.ingestion.stability_checker = FileStabilityChecker(interval_seconds=0, sleep=lambda _: None)
        self.snapshots = UiSnapshotService(self.runtime.database)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def ingest_and_plan(self, capture_id: str) -> str:
        source = self.runtime.paths.inbox / f"{capture_id}.md"
        source.write_bytes(generic_markdown(capture_id=capture_id, title=f"Documento {capture_id}"))
        self.assertTrue(self.runtime.ingestion.ingest(source).accepted)
        return self.runtime.workflow_planner.plan_capture(capture_id)

    def publish(self, capture_id: str, body: str):
        workflow_id = self.ingest_and_plan(capture_id)
        task = self.runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
        self.runtime.workflow_repository.apply_status(task.task_id, {
            "task_id": task.task_id,
            "status": "success",
            "result": {"assistant_content": body},
            "error": None,
        })
        self.runtime.workflow_planner.advance_workflow(workflow_id)
        self.assertEqual(self.runtime.publication.publish_ready(), 1)
        return next(note for note in self.runtime.publication_repository.list_notes_by_status("PUBLISHED")
                    if note.capture_id == capture_id)

    @staticmethod
    def extraction(note, quote: str):
        document = note.vault_path.read_text(encoding="utf-8")
        start = document.index(quote)
        return {
            "claims": [{
                "statement": quote,
                "claim_type": "VERSION",
                "volatility": "HIGH",
                "span_start": start,
                "span_end": start + len(quote),
                "quote": quote,
                "entities": ["Producto X"],
                "observed_at": "2026-06-24T10:00:00Z",
                "source_date": "2026-06-24",
                "manual_lock": False,
            }]
        }

    def test_queue_snapshot_exposes_position_phase_model_elapsed_and_no_percentages(self) -> None:
        workflow_id = self.ingest_and_plan("ui_queue")
        task = self.runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
        self.assertIsNotNone(self.runtime.workflow_repository.claim_submission(task.task_id))
        self.runtime.workflow_repository.mark_accepted(task.task_id, {
            "task_id": "broker_ui_queue",
            "status": "queued",
            "status_url": "/api/v1/tasks/broker_ui_queue",
            "cancel_url": "/api/v1/tasks/broker_ui_queue/cancel",
            "execution_strategy": "single",
            "execution_preset": "fast",
            "selection_mode": "auto",
        })

        queue = self.snapshots.queue()

        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0].position, 1)
        self.assertEqual(queue[0].status, "QUEUED")
        self.assertEqual(queue[0].phase, "queued")
        self.assertEqual(queue[0].model, "llama3.1:8b")
        self.assertGreaterEqual(queue[0].elapsed_seconds, 0)
        self.assertNotIn("%", queue[0].progress_text)

    def test_dashboard_and_review_snapshots_are_read_only_and_actionable(self) -> None:
        old_text = "La versión estable de Producto X es 1.0."
        new_text = "La versión estable de Producto X es 2.0."
        old_note = self.publish("ui_old", "# Estado\n\n" + old_text + "\n")
        self.runtime.semantic_maintenance.ingest_extraction(old_note.note_id, self.extraction(old_note, old_text))
        new_note = self.publish("ui_new", "# Estado\n\n" + new_text + "\n")
        candidate_ids = self.runtime.semantic_maintenance.ingest_extraction(
            new_note.note_id, self.extraction(new_note, new_text)
        )
        candidate_id = candidate_ids[0]
        self.runtime.semantic_maintenance.compare(candidate_id, {
            "relation": "SUPERSEDES",
            "confidence": 0.91,
            "impact": "HIGH",
            "rationale": "La evidencia local nueva declara una versión posterior.",
            "replacement_text": new_text,
        })
        self.runtime.repository.record_event("BROKER_ONLINE", "Broker disponible")

        dashboard = self.snapshots.dashboard()
        reviews = self.snapshots.reviews()

        self.assertEqual(dashboard.pending_review, 1)
        self.assertEqual(dashboard.published_notes, 2)
        self.assertEqual(dashboard.broker_status, "online")
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].candidate_id, candidate_id)
        self.assertIn("-" + old_text, reviews[0].diff_text)

    def test_topics_and_profiles_snapshots_support_phase_seven_tabs(self) -> None:
        topics = self.snapshots.topics()
        profiles = self.snapshots.profiles()

        self.assertTrue(any(topic.name == "_inbox" for topic in topics))
        self.assertTrue(any(profile.name == "Técnico Profundo" for profile in profiles))
        with closing(self.runtime.database.connect()) as connection:
            profile_count = connection.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
        self.assertEqual(len(profiles), profile_count)

    def test_dashboard_uses_existing_pipeline_paths_without_root_attribute(self) -> None:
        self.assertFalse(hasattr(self.runtime.paths, "root"))
        self.assertEqual(data_root_label(self.runtime), str(self.root))
