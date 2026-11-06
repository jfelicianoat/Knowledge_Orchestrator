"""Revisión de usabilidad con los datos reales del usuario (5-nov-2026).

Con 1258 notas en Google Drive, Afirmaciones e Inicio esperaban a releer y
hashear toda la bóveda (432 s en frío) antes de enseñar nada, y la repetían en
cada refresco. Además: enlaces de YouTube sin vídeo, códigos internos en
Actividad y pestañas de filtro cortadas fuera de la vista.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from knowledge_orchestrator.services import provenance
from knowledge_orchestrator.ui import operations_snapshots
from knowledge_orchestrator.ui.dashboard.base import DashboardBase
from knowledge_orchestrator.ui.dashboard.operaciones import OperacionesMixin
from knowledge_orchestrator.ui.dashboard.trabajo import work_filter_key
from knowledge_orchestrator.ui.operations_snapshots import OperationsSnapshots
from knowledge_orchestrator.ui.snapshots import UiSnapshotService
from tests.test_cancelado_broker_2026_10_27 import _row


class _Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path)


class VaultCheckThrottleTests(unittest.TestCase):
    def test_vault_check_due_once_per_interval_and_database(self) -> None:
        clock = [1000.0]
        with patch.object(operations_snapshots.time, "monotonic", lambda: clock[0]), \
                patch.dict(operations_snapshots._last_vault_check, clear=True):
            first = OperationsSnapshots(_Database("a.db"))  # type: ignore[arg-type]
            other = OperationsSnapshots(_Database("b.db"))  # type: ignore[arg-type]
            self.assertTrue(first.vault_check_due())
            self.assertFalse(first.vault_check_due(), "se contrastaba la bóveda en cada refresco")
            self.assertTrue(other.vault_check_due(), "cada base lleva su propio plazo")
            clock[0] += operations_snapshots.VAULT_CHECK_SECONDS
            self.assertTrue(first.vault_check_due())


class _MemoryDatabase:
    def __init__(self, script: str) -> None:
        self.path = Path("memoria.db")
        self._connection = sqlite3.connect(":memory:")
        self._connection.executescript(script)

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        # closing() cierra la conexión: se entrega una copia de la base en memoria.
        copy = sqlite3.connect(":memory:")
        self._connection.backup(copy)
        return copy


class FailedAnalysisTargetsTests(unittest.TestCase):
    def test_only_the_latest_failed_attempt_counts(self) -> None:
        database = _MemoryDatabase(
            "CREATE TABLE notes(note_id, status);"
            "CREATE TABLE update_candidates(candidate_id, status);"
            "CREATE TABLE semantic_jobs(job_id, kind, note_id, candidate_id, status, created_at);"
            "INSERT INTO notes VALUES (1,'PUBLISHED'),(2,'PUBLISHED'),(3,'REJECTED');"
            "INSERT INTO update_candidates VALUES (10,'PENDING_COMPARISON'),(11,'APPLIED');"
            # Nota 1: falló el último intento. Nota 2: falló y luego salió bien. Nota 3: ya no publicada.
            "INSERT INTO semantic_jobs VALUES ('a','EXTRACT',1,NULL,'ERROR','2026-11-01'),"
            "('b','EXTRACT',2,NULL,'ERROR','2026-11-01'),('c','EXTRACT',2,NULL,'SUCCESS','2026-11-02'),"
            "('d','EXTRACT',3,NULL,'ERROR','2026-11-01'),"
            "('e','COMPARE',NULL,10,'ERROR','2026-11-01'),('f','COMPARE',NULL,11,'ERROR','2026-11-01');")
        notes, candidates = OperationsSnapshots(database).failed_analysis_targets()  # type: ignore[arg-type]
        self.assertEqual(notes, [1])
        self.assertEqual(candidates, [10])


class ReopenedDocumentTests(unittest.TestCase):
    def test_reopened_cancelled_document_is_back_in_progress(self) -> None:
        # Tras «Volver a procesar» la captura vuelve a PENDING y su última tarea sigue CANCELLED.
        item = UiSnapshotService._work_item(_row("PENDING", None, "CANCELLED"))
        self.assertEqual(work_filter_key(item), "active")
        self.assertEqual(item.status_label, "En cola local")

    def test_reopened_failed_document_is_back_in_progress(self) -> None:
        item = UiSnapshotService._work_item(_row("PENDING", None, "ERROR"))
        self.assertEqual(work_filter_key(item), "active")


class SingleNoteReconcileTests(unittest.TestCase):
    def test_document_checks_only_the_requested_note(self) -> None:
        from knowledge_orchestrator.services.knowledge_access import KnowledgeAccess

        calls = []
        access = KnowledgeAccess.__new__(KnowledgeAccess)
        access.knowledge = type("K", (), {"reconcile": lambda self, ids=None: calls.append(ids)})()
        access.database = type("D", (), {"connect": lambda self, readonly=False: sqlite3.connect(":memory:")})()
        with self.assertRaises(sqlite3.OperationalError):
            access.document(7)  # la tabla no existe: basta con ver qué se contrastó antes
        self.assertEqual(calls, [[7]], "abrir una nota contrastaba la bóveda entera")


class BrokerCredentialMessageTests(unittest.TestCase):
    def test_rejected_credential_is_told_apart_from_an_unreachable_broker(self) -> None:
        from knowledge_orchestrator.ui.dashboard.inicio import broker_credential_rejected

        self.assertTrue(broker_credential_rejected("Broker HTTP 403"))
        self.assertTrue(broker_credential_rejected("Broker HTTP 401"))
        self.assertFalse(broker_credential_rejected("All connection attempts failed"))
        self.assertFalse(broker_credential_rejected("Broker HTTP 503"))


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Check:
    def __init__(self):
        self.states = []

    def state(self, value):
        self.states.append(value)


class ProviderPrivacyTests(unittest.TestCase):
    def test_local_privacy_unchecks_and_locks_cloud_providers(self) -> None:
        from knowledge_orchestrator.ui.dashboard.configuracion import CLASSIFICATION_LABELS, ConfiguracionMixin

        view = type("V", (), {})()
        view.profile_form = {"classification": _Var(CLASSIFICATION_LABELS["local_only"])}
        view._provider_local = {"lmstudio": True, "ollama": False}
        view._provider_vars = {"lmstudio": _Var(False), "ollama": _Var(True)}
        view._provider_checks = {"lmstudio": _Check(), "ollama": _Check()}
        view._selected_profile_id = 1
        view._sync_profile_buttons = lambda: None
        view.status_var = _Var("")
        ConfiguracionMixin._sync_provider_privacy(view)  # type: ignore[arg-type]
        self.assertFalse(view._provider_vars["ollama"].get(), "la nube seguía marcada con privacidad local")
        self.assertTrue(view._provider_vars["lmstudio"].get(), "sin ningún proveedor no se podía guardar")
        self.assertEqual(view._provider_checks["ollama"].states[-1], ["disabled"])
        self.assertIn("ollama", view.status_var.get())

        view.profile_form["classification"].set(CLASSIFICATION_LABELS["public"])
        ConfiguracionMixin._sync_provider_privacy(view)  # type: ignore[arg-type]
        self.assertEqual(view._provider_checks["ollama"].states[-1], ["!disabled"])


class YoutubeLinkTests(unittest.TestCase):
    def _url(self, raw: str) -> str | None:
        with tempfile.TemporaryDirectory() as folder:
            connection = sqlite3.connect(Path(folder) / "p.db")
            connection.row_factory = sqlite3.Row
            connection.executescript(
                "CREATE TABLE captures(capture_id, title, source_type, source_origin, metadata_json, sha256);"
                "CREATE TABLE source_changes(provenance_json, observed_at, ingestion_id);"
                "CREATE TABLE api_ingestions(ingestion_id, capture_id, markdown_text);")
            connection.execute("INSERT INTO captures VALUES ('c', 't', 'youtube', 'x', ?, 'h')",
                               (json.dumps({"source_url": raw}),))
            try:
                return provenance.source_provenance_in(connection, "c").get("source_url")
            finally:
                connection.close()

    def test_keeps_only_the_video_id(self) -> None:
        self.assertEqual(self._url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42&token=secreto"),
                         "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_other_sites_still_drop_the_query(self) -> None:
        self.assertEqual(self._url("https://example.com/watch?v=abc&token=secreto"), "https://example.com/watch")

    def test_odd_video_ids_are_dropped(self) -> None:
        self.assertEqual(self._url("https://www.youtube.com/watch?v=a%20b"), "https://www.youtube.com/watch")


class _Button:
    def __init__(self, width: int) -> None:
        self.width, self.place = width, {"row": "0", "column": "9"}

    def winfo_reqwidth(self) -> int:
        return self.width

    def grid_info(self) -> dict[str, str]:
        return self.place

    def grid(self, *, row: int, column: int) -> None:
        self.place = {"row": str(row), "column": str(column)}


class ReflowTests(unittest.TestCase):
    def test_buttons_that_do_not_fit_move_to_the_next_row(self) -> None:
        buttons = [_Button(100) for _ in range(5)]
        DashboardBase._reflow_buttons(buttons, 330)  # type: ignore[arg-type]
        self.assertEqual([(b.place["row"], b.place["column"]) for b in buttons],
                         [("0", "0"), ("0", "1"), ("0", "2"), ("1", "0"), ("1", "1")])

    def test_before_first_draw_nothing_moves(self) -> None:
        buttons = [_Button(100)]
        DashboardBase._reflow_buttons(buttons, 1)  # type: ignore[arg-type]
        self.assertEqual(buttons[0].place, {"row": "0", "column": "9"})


class ActivityLabelTests(unittest.TestCase):
    def test_event_codes_are_shown_in_words(self) -> None:
        view = type("View", (), {"_event_label": staticmethod(DashboardBase._event_label)})()
        label = OperacionesMixin._flow_status(view, "SEMANTIC_JOB_STATE_CHANGED")  # type: ignore[arg-type]
        self.assertEqual(label, "Análisis actualizado")
        self.assertEqual(OperacionesMixin._flow_status(view, "PENDING_REVIEW"), "Por revisar")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
