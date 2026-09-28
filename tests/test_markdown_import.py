"""Importar Markdown normal desde el escritorio sin conocer el contrato del plugin."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.domain.contracts import parse_capture_bytes
from knowledge_orchestrator.repositories.capture_repository import CaptureRepository
from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.services.file_stability import FileStabilityChecker
from knowledge_orchestrator.services.ingestion import IngestionService
from knowledge_orchestrator.services.markdown_import import build_capture, inspect_import, write_converted

ORDINARY = "# Apuntes de estocástico\n\nEl %K mide la posición del cierre.\n\n## Transcripción\n\nTexto propio.\n"
CAPTURE = """---
contract_version: "1.0"
capture_id: "yt_20260927_x"
source_type: "document"
title: "Captura ya válida"
captured_at: "2026-09-27T19:15:00Z"
has_transcript: true
status: "pending"
---

## Transcripción

Contenido.
"""


class _Immediate(FileStabilityChecker):
    def wait_until_stable(self, path, *, cancel_event=None):  # type: ignore[no-untyped-def]
        return None


class MarkdownImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.outside = self.root / "descargas"
        self.outside.mkdir()
        self.paths = PipelinePaths.under(self.root / "datos")
        self.paths.ensure_directories()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write(self, name: str, text: str) -> Path:
        path = self.outside / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_ordinary_markdown_is_converted_and_accepted_end_to_end(self) -> None:
        original = self._write("apuntes.md", ORDINARY)
        before = hashlib.sha256(original.read_bytes()).hexdigest()

        candidate = inspect_import(original)
        self.assertEqual(candidate.kind, "ordinary")
        self.assertEqual(candidate.title, "Apuntes de estocástico")
        converted = write_converted(original, self.paths.inbox)

        database = Database(self.paths.database)
        database.initialize()
        repository = CaptureRepository(database)
        result = IngestionService(self.paths, repository, stability_checker=_Immediate()).ingest(converted)

        self.assertTrue(result.accepted, result)
        record = repository.get(result.capture_id or "")
        assert record is not None
        self.assertEqual(record.title, "Apuntes de estocástico")
        # El texto llega entero, incluido un «## Transcripción» propio del documento.
        self.assertIn("El %K mide la posición del cierre.", record.transcript_content)
        self.assertIn("Texto propio.", record.transcript_content)
        self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), before)
        self.assertTrue(original.exists())

    def test_capture_id_is_deterministic_and_frontmatter_title_wins(self) -> None:
        text = "---\ntitle: Nota de Obsidian\ntags: [x]\n---\n\nCuerpo sin encabezado.\n"
        first = self._write("a.md", text)
        second = self._write("b.txt", text)
        id_a, markdown = build_capture(first)
        id_b, _ = build_capture(second)
        self.assertEqual(id_a, id_b)
        document = parse_capture_bytes(markdown.encode("utf-8"))
        self.assertEqual(document.title, "Nota de Obsidian")
        self.assertEqual(document.transcript_content, "Cuerpo sin encabezado.")
        self.assertEqual(inspect_import(second).kind, "ordinary")

    def test_compatible_capture_is_recognised_and_left_unchanged(self) -> None:
        path = self._write("captura.md", CAPTURE)
        candidate = inspect_import(path)
        self.assertEqual(candidate.kind, "compatible")
        self.assertEqual(candidate.title, "Captura ya válida")
        self.assertEqual(path.read_text(encoding="utf-8"), CAPTURE)

    def test_broken_capture_is_explained_not_converted(self) -> None:
        path = self._write("rota.md", CAPTURE.replace('status: "pending"', 'status: "done"'))
        candidate = inspect_import(path)
        self.assertEqual(candidate.kind, "malformed")
        self.assertIn("status", candidate.reason)
        self.assertIn("pending", candidate.reason)

    def test_empty_and_non_utf8_files_are_reported(self) -> None:
        empty = self._write("vacio.md", "   \n")
        self.assertEqual(inspect_import(empty).kind, "unreadable")
        latin = self.outside / "latin.txt"
        latin.write_bytes("canción".encode("latin-1"))
        candidate = inspect_import(latin)
        self.assertEqual(candidate.kind, "unreadable")
        self.assertIn("UTF-8", candidate.reason)


if __name__ == "__main__":
    unittest.main()
