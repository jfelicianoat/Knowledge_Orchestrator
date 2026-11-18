"""16-nov-2026: apuntes dejados en la carpeta vigilada acababan en cuarentena
(«El archivo no tiene el formato de una captura») sin forma de aprovecharlos.
«Importar como apuntes» los publica tal cual y cierra la incidencia.
"""
from __future__ import annotations

from unittest import mock

from knowledge_orchestrator.domain.contracts import parse_capture_bytes
from knowledge_orchestrator.domain.sources import is_own_note
from tests.test_uso_real_2026_10_08 import RuntimeCase, _tk_available


class ImportQuarantinedNotesTests(RuntimeCase):
    def setUp(self) -> None:
        super().setUp()
        _tk_available(self)
        from knowledge_orchestrator.ui.dashboard import OrchestratorDashboard

        self.paths.ensure_directories()
        self.window = OrchestratorDashboard(self.runtime)
        self.window.withdraw()
        self.addCleanup(self.window.destroy)
        self.errors: list[BaseException] = []
        self.window.report_callback_exception = lambda _type, value, _tb: self.errors.append(value)

    def _quarantine(self, name: str, data: bytes, message: str, code: str = "CONTRACT_VALIDATION_FAILED") -> None:
        folder = self.paths.failed / "contracts"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
        self.runtime.repository.record_ingestion_incident(folder / name, code, message)

    def _wait_for_import(self) -> None:
        for _ in range(200):
            self.window.update()
            if "en proceso" in self.window.status_var.get():
                return
            self.window.after(20)
        self.fail(f"la importación no terminó: {self.window.status_var.get()!r}")

    def test_import_all_publishes_ansi_and_utf8_notes_as_own_notes(self) -> None:
        self._quarantine("utf8.md", "## Idea principal\n\nUn resumen hecho a mano.\n".encode("utf-8"),
                         "falta la apertura del frontmatter YAML")
        self._quarantine("ansi.md", "# Título\r\n\r\nInversión estacional\r\n".encode("cp1252"),
                         "el fichero debe usar UTF-8")
        for name in ("copia1.md", "copia2.md"):
            self._quarantine(name, b"x", "Copia de «X», que ya estaba importado (mismo capture_id)", "DUPLICATE_CAPTURE")
        window = self.window
        window._show_page("work")
        window._refresh(force=True)
        window._set_work_filter("attention")
        # Las copias de documentos ya importados se cierran todas de una vez.
        self.assertEqual(window.close_duplicates_button.cget("text"), "Cerrar ya importados (2)")
        with mock.patch("knowledge_orchestrator.ui.dashboard.trabajo_acciones.messagebox") as box:
            box.askyesno.return_value = True
            window._close_all_duplicates()
        self.assertEqual(sorted(i.error_code for i in self.snapshots.work_items() if i.category == "attention"),
                         ["CONTRACT_VALIDATION_FAILED"] * 2)
        self.assertFalse(window.close_duplicates_button.grid_info(), "sin duplicados, el botón se oculta")
        window._set_work_filter("attention")
        self.assertTrue(window.import_notes_button.grid_info())
        self.assertEqual(window.import_notes_button.cget("text"), "Importar como apuntes (2)")
        self.assertEqual(window.retry_button.cget("text"), "Importar como apuntes")
        with mock.patch.object(self.runtime.worker, "submit", return_value=True) as submit, \
                mock.patch("knowledge_orchestrator.ui.dashboard.trabajo_acciones.messagebox") as box:
            box.askyesno.return_value = True
            window._import_all_as_notes()
            self._wait_for_import()
        self.assertEqual(submit.call_count, 2)
        documents = [parse_capture_bytes(call.args[0].read_bytes()) for call in submit.call_args_list]
        self.assertTrue(all(is_own_note(doc.metadata) for doc in documents))
        self.assertTrue(any("Inversión estacional" in doc.transcript_content for doc in documents))
        window._refresh(force=True)
        self.assertEqual([i for i in self.snapshots.work_items() if i.category == "attention"], [])
        self.assertEqual(self.errors, [])
