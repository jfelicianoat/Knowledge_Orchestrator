"""Rediseño 0.3 de la interfaz: la lógica de presentación, sin abrir Tk.

Lo que aquí se fija es lo que el usuario lee: en qué paso está un documento,
qué frase explica su fase, qué tono tiene su estado y qué entra en la
actividad reciente. Un cambio de estilo no debería poder romperlo sin avisar.
"""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.ui.dashboard import NAVIGATION
from knowledge_orchestrator.ui.dashboard.base import DashboardBase, ingestion_status_text
from knowledge_orchestrator.ui.dashboard.configuracion import ConfiguracionMixin
from knowledge_orchestrator.ui.dashboard.inicio import event_tone
from knowledge_orchestrator.ui.dashboard.temas import topic_order_label
from knowledge_orchestrator.ui.dashboard.trabajo_detalle import STEPS, humane_phase, work_progress
from knowledge_orchestrator.ui.snapshots import UiSnapshotService, WorkItem

BASE_ITEM = WorkItem(
    capture_id="c1", incident_id=None, task_id="t1", title="Documento", filename="doc.md",
    path=r"C:\datos\processing\doc.md", status="PROCESSING", status_label="Procesando", category="active",
    phase="processing", model="auto", elapsed_seconds=0, updated_at="2026-09-11T10:00:00+00:00",
    updated_label="10:00:00", attempt=1, error_code=None, error_message="", retryable=False, progress_text="",
)


def item(**changes: object) -> WorkItem:
    return replace(BASE_ITEM, **changes)  # type: ignore[arg-type]


class NavigationTests(unittest.TestCase):
    def test_every_page_appears_once_with_its_existing_key(self) -> None:
        keys = [key for _section, entries in NAVIGATION for key, _label, _icon in entries]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), {"home", "work", "review", "library", "knowledge", "sources",
                                     "operations", "services", "topics", "config"})


class WorkProgressTests(unittest.TestCase):
    def test_active_states_map_to_the_step_they_are_waiting_on(self) -> None:
        self.assertEqual(work_progress(item(status="STAGED")), (0, "active"))
        self.assertEqual(work_progress(item(status="READY")), (2, "waiting"))
        self.assertEqual(work_progress(item(status="QUEUED")), (3, "waiting"))
        self.assertEqual(work_progress(item(status="PROCESSING")), (3, "active"))

    def test_completed_and_cancelled_are_distinct(self) -> None:
        self.assertEqual(work_progress(item(status="COMPLETED", category="completed")), (len(STEPS), "done"))
        self.assertEqual(work_progress(item(status="CANCELLED", category="completed")), (3, "cancelled"))

    def test_failure_is_placed_where_it_happened(self) -> None:
        submission = item(status="ERROR", category="attention", error_code="BROKER_OFFLINE")
        model = item(status="ERROR", category="attention", error_code="MODEL_UNAVAILABLE")
        incident = item(incident_id=4, task_id=None, status="INGESTION_ERROR", category="attention")
        self.assertEqual(work_progress(submission), (2, "failed"))
        self.assertEqual(work_progress(model), (3, "failed"))
        self.assertEqual(work_progress(incident), (1, "failed"))
        self.assertEqual(work_progress(item(task_id=None, status="FAILED", category="attention")), (1, "failed"))


class PhaseTextTests(unittest.TestCase):
    def test_internal_phase_is_never_shown_raw(self) -> None:
        self.assertEqual(humane_phase(item(phase="ready", status="READY")), "Listo para enviarse al Broker")
        self.assertNotIn("ready", humane_phase(item(phase="ready")).lower().split())

    def test_unit_progress_reads_as_parts(self) -> None:
        self.assertIn("2 de 5", humane_phase(item(progress_text="2/5 unidades")))

    def test_broker_explanations_are_kept(self) -> None:
        text = "El Broker reanudará la tarea automáticamente cuando haya memoria disponible."
        self.assertEqual(humane_phase(item(progress_text=text, phase="Esperando memoria")), text)


class LabelsTests(unittest.TestCase):
    def test_reserved_topic_position_is_not_a_number_for_people(self) -> None:
        self.assertEqual(topic_order_label(2_147_483_647), "Último (reserva)")
        self.assertEqual(topic_order_label(3), "3")

    def test_relative_time(self) -> None:
        now = datetime.now(timezone.utc)
        self.assertEqual(DashboardBase._relative_label((now - timedelta(seconds=20)).isoformat()), "ahora mismo")
        self.assertEqual(DashboardBase._relative_label((now - timedelta(minutes=7)).isoformat()), "hace 7 min")
        self.assertEqual(DashboardBase._relative_label((now - timedelta(hours=2, minutes=5)).isoformat()), "hace 2 h")
        self.assertEqual(DashboardBase._relative_label(None), "—")
        self.assertEqual(DashboardBase._relative_label("no es fecha"), "no es fecha")

    def test_row_shows_file_name_not_full_path(self) -> None:
        self.assertEqual(DashboardBase._work_row_text(BASE_ITEM), "Documento\ndoc.md")
        blocked = item(incident_id=2, title="notas.md", filename="notas.md", path=r"C:\inbox\notas.md")
        self.assertEqual(DashboardBase._work_row_text(blocked), "notas.md\nEn la carpeta vigilada")

    def test_tone_never_travels_alone(self) -> None:
        self.assertEqual(DashboardBase._work_tone(item(incident_id=1, category="attention")), "warning")
        self.assertEqual(DashboardBase._work_tone(item(category="attention", status="ERROR")), "error")
        self.assertEqual(DashboardBase._work_tone(item(category="completed", status="COMPLETED")), "success")
        self.assertEqual(DashboardBase._work_tone(item(category="completed", status="CANCELLED")), "neutral")
        self.assertEqual(DashboardBase._work_tone(item(status="READY")), "neutral")
        self.assertEqual(DashboardBase._work_tone(item(status="PROCESSING")), "accent")

    def test_event_tone(self) -> None:
        self.assertEqual(event_tone("CAPTURE_COMPLETED"), "success")
        self.assertEqual(event_tone("BROKER_OFFLINE"), "error")
        self.assertEqual(event_tone("BROKER_RESULT_WARNING"), "warning")
        self.assertEqual(event_tone("CAPTURE_STAGED"), "accent")


class ImportStatusTests(unittest.TestCase):
    def test_import_results_read_as_sentences_not_codes(self) -> None:
        self.assertIn("Documento importado", ingestion_status_text({"accepted": True}, "Captura aceptada"))
        duplicate = ingestion_status_text({"accepted": False, "error_code": "DUPLICATE_CAPTURE"},
                                          "capture_id ya registrado")
        self.assertIn("ya estaba importado", duplicate)
        self.assertNotIn("capture_id", duplicate)
        contract = ingestion_status_text({"accepted": False, "error_code": "CONTRACT_VALIDATION_FAILED"},
                                         "$: falta la apertura del frontmatter YAML")
        self.assertIn("falta la apertura del frontmatter YAML", contract)
        self.assertNotIn("$:", contract)
        self.assertIn("cuarentena", contract)


class ProfileFormTests(unittest.TestCase):
    def test_automatic_refresh_does_not_discard_unsaved_edits(self) -> None:
        """El refresco cada dos segundos reasigna la selección: no debe repintar el formulario."""

        view = SimpleNamespace(
            profiles_tree=SimpleNamespace(selection=lambda: ("7",)),
            _selected_profile_id=7, _profile_dirty=True, _profile_items={},
            runtime=SimpleNamespace(profiles=SimpleNamespace(
                get_profile=lambda _id: self.fail("recargó el perfil y perdería los cambios"))),
        )

        ConfiguracionMixin._select_profile(view)  # type: ignore[arg-type]

        self.assertTrue(view._profile_dirty)


class RecentActivityTests(unittest.TestCase):
    def test_heartbeats_do_not_hide_what_happened(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            runtime = build_runtime(PipelinePaths.under(Path(folder)))
            runtime.repository.record_event("BROKER_ONLINE", "Broker disponible")
            runtime.repository.record_event("KNOWLEDGE_RECONCILED", "Comprobación de coherencia documental")
            runtime.repository.record_event("API_REQUEST", "GET /documents")
            runtime.repository.record_event("FILE_LOCKED", "El archivo está siendo usado por otro proceso")
            activity = UiSnapshotService(runtime.database).recent_activity()
        self.assertEqual([entry.event_type for entry in activity], ["FILE_LOCKED"])
        self.assertIn("otro proceso", activity[0].message)


if __name__ == "__main__":
    unittest.main()
