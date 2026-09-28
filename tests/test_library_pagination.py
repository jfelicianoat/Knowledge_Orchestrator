"""Biblioteca con miles de notas: nada queda fuera de alcance ni de los filtros.

Antes la consulta cortaba en 500 notas sin decirlo y los temas del filtro se
calculaban con ese recorte, así que la nota más antigua no aparecía nunca y un
tema cuyas notas quedaran fuera no se podía ni elegir.
"""
from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.ui.snapshots import LIBRARY_PAGE_SIZE, UiSnapshotService

START = datetime(2026, 1, 1)


class LibraryPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runtime = build_runtime(PipelinePaths.under(self.root))
        self.snapshots = UiSnapshotService(self.runtime.database)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def seed(self, total: int, *, rare_topic_notes: int = 3) -> None:
        """Siembra `total` notas publicadas; las más antiguas son de un tema aparte.

        La nota 0 es la más antigua. Las `rare_topic_notes` primeras pertenecen a
        «Tema raro», que así solo tiene notas fuera de la primera página.
        """

        with self.runtime.database.transaction(immediate=True) as connection:
            common = connection.execute(
                "INSERT INTO topics(name, position, folder) VALUES ('Tema común', 900, 'Comun')"
            ).lastrowid
            rare = connection.execute(
                "INSERT INTO topics(name, position, folder) VALUES ('Tema raro', 901, 'Raro')"
            ).lastrowid
            captures = []
            notes = []
            for index in range(total):
                capture_id = f"lib_{index:05d}"
                topic_id = rare if index < rare_topic_notes else common
                stamp = (START + timedelta(seconds=index)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                captures.append((capture_id, f"Documento {index:05d}", f"sha{index}", f"{capture_id}.md", topic_id))
                notes.append((capture_id, str(self.root / "vault" / f"{capture_id}.md"), topic_id, stamp, stamp))
            connection.executemany(
                "INSERT INTO captures(capture_id, contract_version, source_type, title, status, sha256, "
                "original_filename, metadata_json, transcript_content, topic_id) "
                "VALUES (?, '1.0', 'youtube', ?, 'COMPLETED', ?, ?, '{}', 'texto', ?)",
                captures,
            )
            connection.executemany(
                "INSERT INTO notes(capture_id, revision, vault_path, status, topic_id, published_at, updated_at) "
                "VALUES (?, 1, ?, 'PUBLISHED', ?, ?, ?)",
                notes,
            )

    def walk_all(self, **filters) -> list[str]:
        seen: list[str] = []
        offset = 0
        while True:
            page = self.snapshots.library_page(offset=offset, **filters)
            seen.extend(item.capture_id for item in page.items)
            if not page.has_next:
                return seen
            offset = page.offset + page.limit

    def test_oldest_note_is_reachable_beyond_the_old_limit(self) -> None:
        for total in (501, 5000):
            with self.subTest(total=total):
                self.tearDown()
                self.setUp()
                self.seed(total)
                first = self.snapshots.library_page()
                self.assertEqual(first.total, total)
                self.assertEqual(len(first.items), LIBRARY_PAGE_SIZE)
                seen = self.walk_all()
                self.assertEqual(len(seen), total)
                self.assertEqual(len(set(seen)), total)
                self.assertEqual(seen[-1], "lib_00000")

    def test_range_label_states_the_real_total(self) -> None:
        self.seed(2530)
        first = self.snapshots.library_page()
        self.assertEqual(first.range_label, "1–100 de 2.530")
        last = self.snapshots.library_page(offset=2500)
        self.assertEqual(last.range_label, "2.501–2.530 de 2.530")
        self.assertFalse(last.has_next)
        self.assertTrue(last.has_previous)
        # Una página que ya no existe cae en la última que sí existe.
        self.assertEqual(self.snapshots.library_page(offset=99_999).offset, 2500)

    def test_topic_outside_first_page_is_offered_and_filters(self) -> None:
        self.seed(5000, rare_topic_notes=3)
        first = self.snapshots.library_page()
        self.assertNotIn("Tema raro", {item.topic for item in first.items})
        topics = {topic.name: topic.count for topic in first.topics}
        self.assertEqual(topics, {"Tema común": 4997, "Tema raro": 3})
        rare = self.snapshots.library_page(topic="Tema raro")
        self.assertEqual(rare.total, 3)
        self.assertEqual({item.capture_id for item in rare.items}, {"lib_00000", "lib_00001", "lib_00002"})
        self.assertEqual(rare.range_label, "1–3 de 3")
        # Texto y tema se combinan en la consulta, no sobre una página ya recortada.
        self.assertEqual(self.snapshots.library_page("00001", topic="Tema raro").total, 1)
        self.assertEqual(self.snapshots.library_page("00001", topic="Tema común").total, 0)

    def test_library_page_widgets_page_through_and_filter(self) -> None:
        try:
            probe = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tcl/Tk no disponible: {error}")
        probe.destroy()
        from knowledge_orchestrator.ui.dashboard import OrchestratorDashboard

        self.seed(501, rare_topic_notes=2)
        window = OrchestratorDashboard(self.runtime)
        window.withdraw()
        self.addCleanup(window.destroy)
        window._show_page("library")
        window.update()
        self.assertEqual(len(window.library_tree.get_children()), LIBRARY_PAGE_SIZE)
        self.assertIn("1–100 de 501", window.library_summary_var.get())
        self.assertIn("disabled", window.library_previous_button.state())
        self.assertIn("Tema raro", window._library_topic_buttons)
        self.assertEqual(window._library_topic_buttons["Tema raro"].cget("text"), "Tema raro  2")
        for _ in range(5):
            window._library_next_page()
        self.assertIn("501–501 de 501", window.library_summary_var.get())
        self.assertEqual(window.library_tree.get_children(), (str(self._note_id("lib_00000")),))
        self.assertIn("disabled", window.library_next_button.state())
        window._set_library_topic("Tema raro")
        self.assertEqual(len(window.library_tree.get_children()), 2)
        self.assertIn("1–2 de 2", window.library_summary_var.get())
        window._set_library_topic("Todos los temas")
        window.library_search_var.set("00007")
        window._run_scheduled_library_refresh()
        self.assertEqual(len(window.library_tree.get_children()), 1)
        self.assertIn("1–1 de 1", window.library_summary_var.get())

    def _note_id(self, capture_id: str) -> int:
        with closing(self.runtime.database.connect()) as connection:
            return int(connection.execute(
                "SELECT note_id FROM notes WHERE capture_id = ?", (capture_id,)
            ).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
