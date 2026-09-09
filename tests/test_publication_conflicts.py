from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from knowledge_orchestrator.domain.models import CaptureStatus
from tests import test_phase_four_publication as phase_four


class PublicationConflictTests(unittest.TestCase):
    prepare_success = phase_four.PhaseFourPublicationTests.prepare_success

    @staticmethod
    def pending(runtime):
        return runtime.publication_repository.list_notes_by_status("PUBLISHING", "CONFLICT")[0]

    def assert_conflict(self, runtime, note, content):
        self.assertEqual(note.vault_path.read_bytes(), content)
        self.assertEqual(runtime.publication_repository.get_note(note.note_id).status, "CONFLICT")
        capture = runtime.repository.get(note.capture_id)
        self.assertEqual(capture.last_error_code, "PUBLICATION_CONFLICT")
        self.assertEqual(capture.status, CaptureStatus.PROCESSING)
        self.assertTrue(capture.processing_path.is_file())
        self.assertFalse(note.source_archive_path.exists())
        with closing(runtime.database.connect(readonly=True)) as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM events WHERE capture_id=? AND event_type='PUBLICATION_CONFLICT'",
                (note.capture_id,),
            ).fetchone()[0], 1)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM knowledge_claims WHERE note_id=?", (note.note_id,)
            ).fetchone()[0], 0)

    def test_existing_destination_is_preserved_and_repeated_recovery_records_one_conflict(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _ = self.prepare_success(Path(temporary))
            content = b"Edicion humana que no debe desaparecer."

            def checkpoint(name):
                if name == "publication_intent":
                    note = self.pending(runtime)
                    note.vault_path.parent.mkdir(parents=True, exist_ok=True)
                    note.vault_path.write_bytes(content)

            runtime.publication.checkpoint = checkpoint
            self.assertEqual(runtime.publication.publish_ready(), 0)
            note = self.pending(runtime)
            runtime.publication.checkpoint = lambda name: None
            runtime.publication.recover()
            runtime.publication.recover()
            self.assert_conflict(runtime, note, content)
            preserved = note.vault_path.with_name("Edicion conservada.md")
            note.vault_path.rename(preserved)
            runtime.publication.recover()
            self.assertEqual(preserved.read_bytes(), content)
            self.assertEqual(runtime.publication_repository.get_note(note.note_id).status, "PUBLISHED")
            self.assertIsNone(runtime.repository.get(note.capture_id).last_error_code)
            self.assertEqual(runtime.repository.get(note.capture_id).status, CaptureStatus.COMPLETED)

    def test_separate_writer_wins_race_between_check_and_atomic_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _ = self.prepare_success(Path(temporary))
            original_link = os.link
            content = b"Contenido de otro proceso."

            def concurrent_link(source, target):
                subprocess.run(
                    [sys.executable, "-B", "-c",
                     "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'Contenido de otro proceso.')",
                     str(target)], check=True, capture_output=True,
                )
                original_link(source, target)

            with patch("knowledge_orchestrator.services.publication.os.link", side_effect=concurrent_link):
                self.assertEqual(runtime.publication.publish_ready(), 0)
            note = self.pending(runtime)
            self.assert_conflict(runtime, note, content)
            self.assertIsNotNone(note.temp_path)
            self.assertIn(b"Contenido", note.temp_path.read_bytes())
            self.assertNotEqual(note.temp_path.read_bytes(), content)

    def test_edit_after_publication_crash_is_preserved_during_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _ = self.prepare_success(Path(temporary))

            def checkpoint(name):
                if name == "note_renamed":
                    raise phase_four.SimulatedCrash(name)

            runtime.publication.checkpoint = checkpoint
            with self.assertRaises(phase_four.SimulatedCrash):
                runtime.publication.publish_ready()
            note = self.pending(runtime)
            content = note.vault_path.read_bytes() + b"\nEdicion posterior a la caida."
            note.vault_path.write_bytes(content)
            runtime.publication.checkpoint = lambda name: None
            runtime.publication.recover()
            self.assert_conflict(runtime, note, content)

    def test_recovery_detaches_leftover_link_before_recreating_a_moved_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _ = self.prepare_success(Path(temporary))
            original_link = os.link

            def interrupted_link(source, target):
                original_link(source, target)
                raise phase_four.SimulatedCrash("after_link")

            with patch("knowledge_orchestrator.services.publication.os.link", side_effect=interrupted_link):
                with self.assertRaises(phase_four.SimulatedCrash):
                    runtime.publication.publish_ready()
            note = self.pending(runtime)
            preserved = note.vault_path.with_name("Nota movida.md")
            note.vault_path.rename(preserved)
            preserved.write_bytes(b"Edicion que conserva el otro enlace.")
            runtime.publication.recover()
            self.assertEqual(preserved.read_bytes(), b"Edicion que conserva el otro enlace.")
            self.assertIn(b"# Resultado", note.vault_path.read_bytes())
            self.assertFalse(note.temp_path.exists())
            self.assertEqual(runtime.publication_repository.get_note(note.note_id).status, "PUBLISHED")

    def test_one_conflict_does_not_block_other_pending_publications(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _ = self.prepare_success(Path(temporary), "first_conflict")
            second, _ = self.prepare_success(Path(temporary), "second_success")

            def checkpoint(name):
                if name == "publication_intent":
                    note = self.pending(runtime)
                    if note.capture_id == "first_conflict":
                        note.vault_path.parent.mkdir(parents=True, exist_ok=True)
                        note.vault_path.write_bytes(b"Conservar.")

            second.publication.checkpoint = checkpoint
            self.assertEqual(second.publication.publish_ready(), 1)
            self.assertEqual(second.repository.get("second_success").status, CaptureStatus.COMPLETED)
            self.assertEqual(second.repository.get("first_conflict").last_error_code, "PUBLICATION_CONFLICT")

    def test_repeating_completed_publication_without_temp_path_keeps_note_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _ = self.prepare_success(Path(temporary))
            workflow = runtime.publication_repository.list_publishable()[0]
            note = runtime.publication.publish(workflow)
            content = note.vault_path.read_bytes()
            self.assertIsNone(note.temp_path)
            repeated = runtime.publication.publish(workflow)
            self.assertEqual(repeated.note_id, note.note_id)
            self.assertEqual(note.vault_path.read_bytes(), content)
