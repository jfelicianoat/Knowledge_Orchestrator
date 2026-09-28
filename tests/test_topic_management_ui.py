"""Organización permite gestionar temas sin tocar SQLite (auditoría H15)."""
from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.ui.dashboard import OrchestratorDashboard
from knowledge_orchestrator.ui.dashboard.temas import parse_keywords, topic_error_text


class TopicManagementUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.runtime = build_runtime(PipelinePaths.under(Path(self.temporary.name)))
        try:
            probe = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tcl/Tk no disponible: {error}")
        probe.destroy()
        self.window = OrchestratorDashboard(self.runtime)
        self.window.withdraw()
        self.addCleanup(self.window.destroy)
        self.window._refresh_topics()

    def fill(self, *, name: str, keywords: str, folder: str = "") -> None:
        window = self.window
        window._new_topic()
        window.topic_form["name"].set(name)
        window.topic_form["folder"].set(folder)
        window.topic_keywords_text.delete("1.0", "end")
        window.topic_keywords_text.insert("1.0", keywords)

    def topic(self, name: str):
        return next(item for item in self.runtime.topics.list_topics() if item.name == name)

    def test_creates_edits_and_disables_a_topic_from_the_form(self) -> None:
        self.fill(name="Trading", keywords="estocástico, RSI\nETF")
        self.assertTrue(self.window._save_topic_form())
        created = self.topic("Trading")
        self.assertEqual(created.keywords, ("estocástico", "RSI", "ETF"))
        self.assertEqual(created.folder, "Trading")  # carpeta vacía = nombre del tema
        self.assertTrue((self.runtime.paths.obsidian_vault / "Trading").is_dir())
        self.assertIn(str(created.topic_id), self.window.topics_tree.get_children())

        self.window.topics_tree.selection_set(str(created.topic_id))
        self.window._select_topic()
        self.assertEqual(self.window.topic_form["name"].get(), "Trading")
        self.window.topic_form["folder"].set("Finanzas/Trading")
        self.window.topic_form["enabled"].set(False)
        self.window.topic_keywords_text.delete("1.0", "end")
        self.window.topic_keywords_text.insert("1.0", "bolsa")
        self.assertTrue(self.window._save_topic_form())
        edited = self.topic("Trading")
        self.assertEqual((edited.folder, edited.keywords, edited.enabled), ("Finanzas/Trading", ("bolsa",), False))
        self.assertEqual(edited.topic_id, created.topic_id)

    def test_invalid_input_is_explained_in_spanish_and_nothing_is_saved(self) -> None:
        before = len(self.runtime.topics.list_topics())
        self.fill(name="Sin palabras", keywords="")
        self.assertFalse(self.window._save_topic_form())
        self.assertIn("palabra clave", self.window.topic_feedback_var.get())
        self.fill(name="Ruta mala", keywords="x", folder="../fuera")
        self.assertFalse(self.window._save_topic_form())
        self.assertIn("ruta relativa", self.window.topic_feedback_var.get())
        self.assertEqual(len(self.runtime.topics.list_topics()), before)

        self.fill(name="Doble", keywords="uno")
        self.assertTrue(self.window._save_topic_form())
        self.fill(name="Doble", keywords="dos", folder="Otra")
        self.assertFalse(self.window._save_topic_form())
        self.assertEqual(self.window.topic_feedback_var.get(), "Ya existe un tema con ese nombre.")

    def test_reorders_priority_and_the_probe_follows_the_new_order(self) -> None:
        self.fill(name="Primero", keywords="claude")
        self.assertTrue(self.window._save_topic_form())
        self.fill(name="Segundo", keywords="claude, ia")
        self.assertTrue(self.window._save_topic_form())
        self.window.topic_probe_var.set("Cómo usar Claude mejor")
        self.assertIn("Primero", self.window.topic_probe_result.get())

        second = self.topic("Segundo")
        self.window.topics_tree.selection_set(str(second.topic_id))
        self.window._select_topic()
        self.window._move_topic(-1)
        self.assertLess(self.topic("Segundo").position, self.topic("Primero").position)
        self.assertEqual(self.topic("_inbox").position, 2_147_483_647)
        self.assertIn("Segundo", self.window.topic_probe_result.get())

        self.window.topic_probe_var.set("Recetas de cocina")
        self.assertIn("_inbox", self.window.topic_probe_result.get())

    def test_reserved_inbox_only_lets_the_profile_change(self) -> None:
        inbox = self.topic("_inbox")
        self.window.topics_tree.selection_set(str(inbox.topic_id))
        self.window._select_topic()
        self.assertIn("disabled", self.window.topic_name_entry.state())
        self.assertIn("disabled", self.window.topic_up_button.state())
        self.assertTrue(self.window._save_topic_form())
        after = self.topic("_inbox")
        self.assertEqual((after.folder, after.keywords, after.position), ("_inbox", (), 2_147_483_647))

    def test_helpers(self) -> None:
        self.assertEqual(parse_keywords(" a, ,b\nc "), ("a", "b", "c"))
        self.assertEqual(topic_error_text(ValueError("otro")), "otro")


if __name__ == "__main__":
    unittest.main()
