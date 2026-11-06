"""Documento publicado cuyo original desapareció de processing (27-oct-2026).

Antes la captura quedaba en PROCESSING para siempre (ARCHIVE_RECOVERY_FAILED en
cada arranque) y «Cancelar procesamiento» no encontraba nada que cancelar.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knowledge_orchestrator.domain.models import CaptureStatus
from knowledge_orchestrator.services.publication import PublicationService
from tests import test_phase_four_publication as fase4


class FuenteDesaparecidaTests(unittest.TestCase):
    def test_published_note_without_source_completes_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime, _ = fase4.PhaseFourPublicationTests.prepare_success(self, Path(temporary), "document_gone")

            def checkpoint(name: str) -> None:
                if name == "note_persisted":
                    raise fase4.SimulatedCrash(name)

            crashing = PublicationService(
                runtime.paths, runtime.repository, runtime.domain_repository,
                runtime.publication_repository, runtime.workflow_planner, checkpoint=checkpoint,
            )
            with self.assertRaises(fase4.SimulatedCrash):
                crashing.publish_ready()
            capture = runtime.repository.get("document_gone")
            capture.processing_path.unlink()

            runtime.publication.recover()
            capture = runtime.repository.get("document_gone")
            self.assertEqual(capture.status, CaptureStatus.COMPLETED)
            self.assertIsNone(capture.archive_path)


if __name__ == "__main__":
    unittest.main()
