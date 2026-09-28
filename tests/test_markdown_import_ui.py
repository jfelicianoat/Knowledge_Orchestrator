"""«Importar documentos» convierte Markdown normal y no bloquea la ventana."""
from __future__ import annotations

import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from knowledge_orchestrator.config import BrokerSettings, PipelinePaths
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.ui.dashboard import OrchestratorDashboard, trabajo_acciones
from tests.test_markdown_import import CAPTURE, ORDINARY


class MarkdownImportUiTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            probe = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tcl/Tk no disponible: {error}")
        probe.destroy()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime = build_runtime(
            PipelinePaths.under(self.root / "datos"), broker_settings=BrokerSettings(base_url="http://127.0.0.1:9"),
        )
        self.window = OrchestratorDashboard(self.runtime)
        self.window.withdraw()
        self.addCleanup(self.window.destroy)
        self.outside = self.root / "descargas"
        self.outside.mkdir()

    def _pump_until(self, predicate, timeout: float = 5.0) -> None:  # type: ignore[no-untyped-def]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.window.update()
            if predicate():
                return
            time.sleep(0.02)
        self.fail(f"No terminó a tiempo; estado: {self.window.status_var.get()}")

    def _import(self, files: list[Path], *, convert: bool) -> tuple[mock.Mock, mock.Mock]:
        warnings, errors = mock.Mock(), mock.Mock()
        with mock.patch.object(trabajo_acciones.filedialog, "askopenfilenames", return_value=[str(f) for f in files]), \
                mock.patch.object(trabajo_acciones.messagebox, "showwarning", warnings), \
                mock.patch.object(trabajo_acciones.messagebox, "showerror", errors), \
                mock.patch.object(self.window, "_confirm_conversion", return_value=convert) as confirm:
            self.window._import_documents()
            self._pump_until(lambda: "añadid" in self.window.status_var.get()
                             or "ningún documento" in self.window.status_var.get())
        self.confirm = confirm
        return warnings, errors

    def test_ordinary_file_is_converted_after_one_confirmation_and_capture_copied(self) -> None:
        ordinary = self.outside / "apuntes.md"
        ordinary.write_text(ORDINARY, encoding="utf-8")
        capture = self.outside / "captura.md"
        capture.write_text(CAPTURE, encoding="utf-8")
        broken = self.outside / "rota.md"
        broken.write_text(CAPTURE.replace('status: "pending"', 'status: "done"'), encoding="utf-8")

        warnings, errors = self._import([ordinary, capture, broken], convert=True)

        self.confirm.assert_called_once()
        self.assertEqual([item.path.name for item in self.confirm.call_args.args[0]], ["apuntes.md"])
        warnings.assert_called_once()
        self.assertIn("rota.md", warnings.call_args.args[1])
        self.assertIn("parece una captura", warnings.call_args.args[1])
        errors.assert_not_called()
        inbox = sorted(path.name for path in self.runtime.paths.inbox.glob("*.md"))
        self.assertIn("captura.md", inbox)
        self.assertTrue(any(name.startswith("manual_") for name in inbox))
        self.assertNotIn("rota.md", inbox)
        self.assertEqual(ordinary.read_text(encoding="utf-8"), ORDINARY)
        self.assertIn("2 documentos añadidos", self.window.status_var.get())

    def test_declining_conversion_adds_nothing(self) -> None:
        ordinary = self.outside / "notas.txt"
        ordinary.write_text("Solo texto.\n", encoding="utf-8")
        self._import([ordinary], convert=False)
        self.assertEqual(list(self.runtime.paths.inbox.glob("*.md")), [])
        self.assertIn("No se añadió ningún documento", self.window.status_var.get())


if __name__ == "__main__":
    unittest.main()
