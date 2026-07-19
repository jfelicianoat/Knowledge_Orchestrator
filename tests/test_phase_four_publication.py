from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.domain.models import CaptureStatus
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.file_stability import FileStabilityChecker
from knowledge_orchestrator.services.publication import PublicationError, PublicationService, validate_result_markdown
from tests.helpers import generic_markdown


class SimulatedCrash(RuntimeError):
    pass


class PhaseFourPublicationTests(unittest.TestCase):
    def prepare_success(self, root: Path, capture_id: str = "document_publish"):
        runtime = build_runtime(PipelinePaths.under(root))
        runtime.ingestion.stability_checker = FileStabilityChecker(interval_seconds=0, sleep=lambda _: None)
        source = runtime.paths.inbox / f"{capture_id}.md"
        source.write_bytes(generic_markdown(capture_id=capture_id, title="Guía: Python / Windows"))
        result = runtime.ingestion.ingest(source)
        self.assertTrue(result.accepted)
        workflow_id = runtime.workflow_planner.plan_capture(capture_id)
        task = runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
        runtime.workflow_repository.apply_status(task.task_id, {
            "task_id": task.task_id,
            "status": "success",
            "result": {"assistant_content": "# Resultado\n\nContenido útil."},
            "error": None,
        })
        runtime.workflow_planner.advance_workflow(workflow_id)
        return runtime, workflow_id

    def test_validates_body_and_builds_safe_frontmatter_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _ = self.prepare_success(Path(temporary))
            self.assertEqual(runtime.publication.publish_ready(), 1)
            notes = runtime.publication_repository.list_notes_by_status("PUBLISHED")
            self.assertEqual(len(notes), 1)
            note = notes[0]
            self.assertTrue(note.vault_path.is_file())
            self.assertNotIn(":", note.vault_path.name)
            text = note.vault_path.read_text(encoding="utf-8")
            frontmatter = yaml.safe_load(text.split("---", 2)[1])
            self.assertEqual(frontmatter["capture_id"], "document_publish")
            self.assertEqual(frontmatter["revision"], 1)
            self.assertIn("# Resultado", text)
            capture = runtime.repository.get("document_publish")
            self.assertEqual(capture.status, CaptureStatus.COMPLETED)
            self.assertTrue(note.source_archive_path.is_file())
            self.assertFalse(capture.processing_path)

    def test_rejects_llm_frontmatter(self) -> None:
        with self.assertRaises(PublicationError):
            validate_result_markdown("---\ntitle: inyectado\n---\nTexto")

    def test_recovers_crash_after_note_rename(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _ = self.prepare_success(Path(temporary), "document_crash_note")

            def checkpoint(name: str) -> None:
                if name == "note_renamed":
                    raise SimulatedCrash(name)

            crashing = PublicationService(
                runtime.paths, runtime.repository, runtime.domain_repository,
                runtime.publication_repository, runtime.workflow_planner, checkpoint=checkpoint,
            )
            with self.assertRaises(SimulatedCrash):
                crashing.publish_ready()
            self.assertEqual(len(runtime.publication_repository.list_notes_by_status("PUBLISHING")), 1)

            runtime.publication.recover()
            note = runtime.publication_repository.list_notes_by_status("PUBLISHED")[0]
            self.assertTrue(note.vault_path.exists())
            self.assertTrue(note.source_archive_path.exists())
            self.assertEqual(runtime.repository.get("document_crash_note").status, CaptureStatus.COMPLETED)

    def test_recovers_crash_after_source_move(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _ = self.prepare_success(Path(temporary), "document_crash_source")

            def checkpoint(name: str) -> None:
                if name == "source_archived":
                    raise SimulatedCrash(name)

            crashing = PublicationService(
                runtime.paths, runtime.repository, runtime.domain_repository,
                runtime.publication_repository, runtime.workflow_planner, checkpoint=checkpoint,
            )
            with self.assertRaises(SimulatedCrash):
                crashing.publish_ready()
            note = runtime.publication_repository.list_notes_by_status("PUBLISHED")[0]
            self.assertTrue(note.source_archive_path.exists())
            self.assertEqual(runtime.repository.get("document_crash_source").status, CaptureStatus.PROCESSING)

            runtime.publication.recover()
            self.assertEqual(runtime.repository.get("document_crash_source").status, CaptureStatus.COMPLETED)

    def test_rejection_preserves_note_and_source_then_reprocesses_revision_two(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _ = self.prepare_success(Path(temporary), "document_review")
            runtime.publication.publish_ready()
            note = runtime.publication_repository.list_notes_by_status("PUBLISHED")[0]

            rejected = runtime.publication.reject(note.note_id)
            capture = runtime.repository.get("document_review")
            self.assertEqual(rejected.status, "REJECTED")
            self.assertEqual(capture.status, CaptureStatus.REJECTED)
            self.assertTrue(rejected.rejected_path.exists())
            self.assertTrue(capture.rejected_source_path.exists())
            self.assertFalse(note.vault_path.exists())

            workflow_id = runtime.publication.reprocess(note.note_id)
            self.assertEqual(workflow_id, "wf_document_review_r2")
            capture = runtime.repository.get("document_review")
            self.assertEqual(capture.status, CaptureStatus.SUBMITTING)
            self.assertTrue(capture.processing_path.exists())
            self.assertTrue(capture.rejected_source_path.exists())
            task = runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
            self.assertIn(":2:", task.idempotency_key)
            runtime.workflow_repository.apply_status(task.task_id, {
                "task_id": task.task_id,
                "status": "success",
                "result": {"assistant_content": "# Resultado revisado"},
                "error": None,
            })
            runtime.workflow_planner.advance_workflow(workflow_id)
            self.assertEqual(runtime.publication.publish_ready(), 1)
            published_r2 = runtime.publication_repository.list_notes_by_status("PUBLISHED")[0]
            self.assertEqual(published_r2.revision, 2)
            self.assertTrue(published_r2.vault_path.exists())
            self.assertEqual(runtime.repository.get("document_review").status, CaptureStatus.COMPLETED)

    def test_recovers_rejection_after_note_was_already_moved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _ = self.prepare_success(Path(temporary), "document_reject_crash")
            runtime.publication.publish_ready()
            note = runtime.publication_repository.list_notes_by_status("PUBLISHED")[0]

            def checkpoint(name: str) -> None:
                if name == "note_rejected_move":
                    raise SimulatedCrash(name)

            crashing = PublicationService(
                runtime.paths, runtime.repository, runtime.domain_repository,
                runtime.publication_repository, runtime.workflow_planner, checkpoint=checkpoint,
            )
            with self.assertRaises(SimulatedCrash):
                crashing.reject(note.note_id)
            self.assertEqual(runtime.publication_repository.get_note(note.note_id).status, "REJECTING")

            runtime.publication.recover()
            recovered = runtime.publication_repository.get_note(note.note_id)
            self.assertEqual(recovered.status, "REJECTED")
            self.assertTrue(recovered.rejected_path.exists())
            self.assertTrue(runtime.repository.get(note.capture_id).rejected_source_path.exists())

    def test_recovers_reprocess_after_copy_before_database_transition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _ = self.prepare_success(Path(temporary), "document_reprocess_crash")
            runtime.publication.publish_ready()
            note = runtime.publication_repository.list_notes_by_status("PUBLISHED")[0]
            runtime.publication.reject(note.note_id)

            def checkpoint(name: str) -> None:
                if name == "reprocess_copied":
                    raise SimulatedCrash(name)

            crashing = PublicationService(
                runtime.paths, runtime.repository, runtime.domain_repository,
                runtime.publication_repository, runtime.workflow_planner, checkpoint=checkpoint,
            )
            with self.assertRaises(SimulatedCrash):
                crashing.reprocess(note.note_id)
            intents = runtime.publication_repository.list_reprocess_intents("PREPARED")
            self.assertEqual(len(intents), 1)
            self.assertTrue(intents[0].target_path.exists())

            runtime.publication.recover()
            self.assertIsNotNone(runtime.workflow_repository.get_workflow("wf_document_reprocess_crash_r2"))
            self.assertEqual(
                runtime.publication_repository.list_reprocess_intents("PLANNED")[0].revision,
                2,
            )


if __name__ == "__main__":
    unittest.main()
