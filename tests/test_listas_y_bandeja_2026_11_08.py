"""Peticiones del 8-nov-2026 en Documentos y la carpeta vigilada.

- La lista volvía arriba en cada refresco (no se podía llegar al final).
- Lo nuevo no subía arriba hasta cambiar de pestaña.
- «Enviar todos» en «Necesitan atención».
- Congelar/descongelar la ingesta de la carpeta vigilada.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from unittest import mock

from knowledge_orchestrator.ui.dashboard.base import DashboardBase
from knowledge_orchestrator.worker.inbox_watcher import InboxWatcher
from tests import test_reenvio_2026_10_25 as reenvio
from tests.helpers import valid_markdown
from tests.test_uso_real_2026_10_08 import RuntimeCase, _tk_available


class ReplaceTreeOrderTests(RuntimeCase):
    def test_existing_rows_follow_the_new_order(self) -> None:
        _tk_available(self)
        root = tk.Tk()
        self.addCleanup(root.destroy)
        tree = ttk.Treeview(root)
        DashboardBase._replace_tree(tree, [("a", ()), ("b", ())])
        DashboardBase._replace_tree(tree, [("c", ()), ("b", ()), ("a", ())])
        self.assertEqual(tree.get_children(), ("c", "b", "a"))


class InboxPauseTests(RuntimeCase):
    def test_frozen_inbox_leaves_the_file_until_unfrozen(self) -> None:
        watcher: InboxWatcher = self.runtime.watcher
        self.paths.ensure_directories()
        (self.paths.inbox / "a.md").write_bytes(valid_markdown(capture_id="yt_pausa_001"))
        with mock.patch.object(watcher.worker, "submit", return_value=True) as submit:
            watcher.set_paused(True)
            self.assertEqual(watcher.scan_once(), 0)
            self.assertFalse(watcher._submit(self.paths.inbox / "a.md"), "el evento de watchdog también se ignora")
            submit.assert_not_called()
            watcher.set_paused(False)
            self.assertEqual(watcher.scan_once(), 1)


class WorkListTests(RuntimeCase):
    chunked_document = reenvio.ResendFailedDocumentTests.chunked_document

    def setUp(self) -> None:
        super().setUp()
        _tk_available(self)
        from knowledge_orchestrator.ui.dashboard import OrchestratorDashboard

        self.window = OrchestratorDashboard(self.runtime)
        self.window.withdraw()
        self.addCleanup(self.window.destroy)
        self.errors: list[BaseException] = []
        self.window.report_callback_exception = lambda _type, value, _tb: self.errors.append(value)

    def test_refresh_does_not_scroll_back_to_the_selection(self) -> None:
        self.chunked_document("doc1", "MODEL_ERROR")
        window = self.window
        window._show_page("work")
        window._refresh(force=True)
        window._set_work_filter("attention")
        self.assertTrue(window._selected_work_ids)
        with mock.patch.object(window.work_tree, "see") as see:
            window._refresh(force=True)
            window.update()
        see.assert_not_called()

    def test_send_all_attention_resends_every_document(self) -> None:
        self.chunked_document("doc1", "MODEL_ERROR")
        self.chunked_document("doc2", "MODEL_ERROR")
        window = self.window
        window._show_page("work")
        window._refresh(force=True)
        window._set_work_filter("attention")
        self.assertTrue(window.send_all_button.grid_info(), "el botón solo se ve en esta pestaña")
        self.assertEqual(window.send_all_button.cget("text"), "Enviar todos (2)")
        with mock.patch("knowledge_orchestrator.ui.dashboard.trabajo_acciones.messagebox") as box:
            box.askyesno.return_value = True
            window._send_all_attention()
        left = [i for i in self.snapshots.work_items() if i.category == "attention"]
        self.assertEqual(left, [])
        self.assertEqual(self.errors, [])

    def test_freeze_button_toggles_the_watcher(self) -> None:
        window = self.window
        window._toggle_inbox_pause()
        self.assertTrue(self.runtime.watcher.paused.is_set())
        self.assertIn("Descongelar", window.inbox_pause_button.cget("text"))
        window._toggle_inbox_pause()
        self.assertFalse(self.runtime.watcher.paused.is_set())
