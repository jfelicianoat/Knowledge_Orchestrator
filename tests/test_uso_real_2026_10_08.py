"""Regresiones de la prueba de uso real del 8-oct-2026 (ventana real + Broker real).

Cada caso reproduce lo que vio la persona usuaria, no un detalle interno:
un botón que no hacía nada, un fichero que desaparecía sin aviso, una lista de
modelos vacía y un formulario que se borraba solo.
"""
from __future__ import annotations

import queue
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from knowledge_orchestrator.config import BrokerSettings, PipelinePaths
from knowledge_orchestrator.integrations.broker_client import (
    MODELS_TIMEOUT_SECONDS,
    BrokerClient,
    TransientBrokerError,
)
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.file_stability import FileStabilityChecker
from knowledge_orchestrator.ui.snapshots import UiSnapshotService
from tests.helpers import generic_markdown


def _tk_available(test: unittest.TestCase) -> None:
    try:
        probe = tk.Tk()
    except tk.TclError as error:
        test.skipTest(f"Tcl/Tk no disponible: {error}")
    probe.destroy()


class RuntimeCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.paths = PipelinePaths.under(Path(self.temporary.name))
        self.runtime = build_runtime(self.paths, broker_settings=BrokerSettings(base_url="http://127.0.0.1:9"))
        self.runtime.ingestion.stability_checker = FileStabilityChecker(interval_seconds=0, sleep=lambda _: None)
        self.snapshots = UiSnapshotService(self.runtime.database)


class QuarantineVisibilityTests(RuntimeCase):
    """Un fichero roto en la bandeja tiene que verse en «Necesitan atención»."""

    def drop(self, name: str, content: bytes) -> Path:
        self.paths.ensure_directories()
        path = self.paths.inbox / name
        path.write_bytes(content)
        return path

    def test_broken_capture_in_inbox_becomes_a_visible_non_retryable_incident(self) -> None:
        path = self.drop("rota.md", b'---\ncontract_version: "1.0"\ncapture_id: "rota"\n---\nsin transcripcion\n')
        result = self.runtime.ingestion.ingest(path)
        self.assertFalse(result.accepted)
        self.assertFalse(path.exists())  # se apartó a cuarentena, sin borrarse

        items = [item for item in self.snapshots.work_items() if item.incident_id is not None]
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.category, "attention")
        self.assertEqual(item.status_label, "Formato no válido")
        self.assertFalse(item.retryable)
        self.assertTrue(Path(item.path).exists())
        self.assertTrue(Path(item.path).is_relative_to(self.paths.failed))
        self.assertIn("Transcripción", item.error_message)

        self.assertTrue(self.runtime.repository.ignore_ingestion_incident(item.incident_id))
        self.assertFalse([i for i in self.snapshots.work_items() if i.incident_id is not None])

    def test_a_duplicate_is_not_an_incident(self) -> None:
        content = generic_markdown(capture_id="doble", title="Doble", transcript="Texto aportado.")
        first = self.drop("doble.md", content)
        self.assertTrue(self.runtime.ingestion.ingest(first).accepted)
        second = self.drop("doble (2).md", content)
        self.assertEqual(self.runtime.ingestion.ingest(second).error_code, "DUPLICATE_CAPTURE")
        self.assertFalse([i for i in self.snapshots.work_items() if i.incident_id is not None])

    def test_quarantine_incident_cannot_be_resent_but_a_locked_file_can(self) -> None:
        from knowledge_orchestrator.ui.dashboard.trabajo_detalle import DetalleMixin

        path = self.drop("rota.md", b"---\ncontract_version: \"1.0\"\n---\nnada\n")
        self.runtime.ingestion.ingest(path)
        locked = self.paths.inbox / "bloqueado.md"
        locked.write_bytes(b"x")
        self.runtime.repository.record_ingestion_incident(locked, "FILE_LOCKED", "En uso por otro programa")
        items = {item.error_code: item for item in self.snapshots.work_items() if item.incident_id}
        self.assertFalse(DetalleMixin._can_send_item(items["CONTRACT_VALIDATION_FAILED"]))
        self.assertTrue(DetalleMixin._can_send_item(items["FILE_LOCKED"]))


class ModelCatalogDiscoveryTests(RuntimeCase):
    """El catálogo lento no puede dejar Ajustes sin modelos ni la barra en «con incidencia»."""

    def test_models_request_uses_its_own_longer_timeout(self) -> None:
        client = BrokerClient(BrokerSettings(base_url="http://127.0.0.1:9"))
        response = mock.Mock(status_code=200)
        response.json.return_value = {"models": []}

        async def fake_request(method, url, **kwargs):
            fake_request.kwargs = kwargs
            return response

        import asyncio

        with mock.patch.object(client, "_request", fake_request):
            asyncio.run(client.list_models())
        self.assertGreaterEqual(fake_request.kwargs["timeout"], MODELS_TIMEOUT_SECONDS)

    def test_failed_discovery_retries_soon_and_does_not_mark_the_broker_offline(self) -> None:
        worker = self.runtime.broker_worker
        worker.settings = BrokerSettings(base_url="http://127.0.0.1:9", dispatcher_interval_seconds=0.02,
                                         health_interval_seconds=0.02)
        worker._DISCOVERY_RETRY_SECONDS = 0.05
        events: queue.Queue = queue.Queue()
        worker.events = events
        calls = []

        async def health() -> None:
            worker._broker_online = True

        async def nothing(*_args, **_kwargs):
            return 0

        async def refresh() -> int:
            calls.append(time.monotonic())
            if len(calls) == 1:
                raise TransientBrokerError("ReadTimeout")
            return 176

        with mock.patch.object(worker, "_check_health", health), \
                mock.patch.object(worker, "_refresh_capabilities", nothing), \
                mock.patch.object(worker.dispatcher, "dispatch_once", nothing), \
                mock.patch.object(worker.poller, "poll_once", nothing), \
                mock.patch.object(worker, "_cancel_requested_tasks", nothing), \
                mock.patch.object(worker.discovery, "refresh", refresh):
            worker.start()
            deadline = time.monotonic() + 5
            while len(calls) < 2 and time.monotonic() < deadline:
                time.sleep(0.02)
            worker.stop(timeout=5)
        kinds = []
        while not events.empty():
            kinds.append(events.get().event_type)
        self.assertEqual(len(calls), 2, "tras un fallo el catálogo se reintenta pronto, no a los 5 minutos")
        self.assertIn("BROKER_MODELS_UNAVAILABLE", kinds)
        self.assertIn("BROKER_MODELS_UPDATED", kinds)
        self.assertNotIn("BROKER_OFFLINE", kinds)


class DashboardInteractionTests(RuntimeCase):
    def setUp(self) -> None:
        super().setUp()
        _tk_available(self)
        from knowledge_orchestrator.ui.dashboard import OrchestratorDashboard

        self.window = OrchestratorDashboard(self.runtime)
        self.window.withdraw()
        self.addCleanup(self.window.destroy)
        self.errors: list[BaseException] = []
        self.window.report_callback_exception = lambda _type, value, _tb: self.errors.append(value)

    def test_review_folders_button_on_home_opens_settings(self) -> None:
        button = next(widget for widget in _walk(self.window.pages["home"])
                      if _text(widget) == "Revisar carpetas")
        button.invoke()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.window._current_page, "config")

    def test_periodic_refresh_does_not_wipe_unsaved_topic_edits(self) -> None:
        window = self.window
        window._refresh_topics()
        window._new_topic()
        window.topic_form["name"].set("Programación")
        window.topic_keywords_text.insert("1.0", "python")
        self.assertTrue(window._save_topic_form())
        window.update()
        # La persona sigue escribiendo en el tema que edita…
        window.topic_keywords_text.delete("1.0", "end")
        window.topic_keywords_text.insert("1.0", "python, gil, asyncio")
        window.topic_form["folder"].set("Código/Python")
        # …y llega el refresco automático.
        for _ in range(3):
            window._refresh(force=True)
            window.update()
        self.assertEqual(window.topic_keywords_text.get("1.0", "end").strip(), "python, gil, asyncio")
        self.assertEqual(window.topic_form["folder"].get(), "Código/Python")
        self.assertEqual(self.errors, [])

    def test_start_api_click_during_a_status_read_is_not_lost(self) -> None:
        from types import SimpleNamespace

        window = self.window
        window._startup = SimpleNamespace(done=True, error=None)
        self.runtime.api_server.consumers.create("lector", ["read"], reserved_names=())

        def pump(predicate, timeout=10.0):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                window.update()
                if predicate():
                    return True
                time.sleep(0.02)
            return False

        window._refresh_services()
        self.assertTrue(pump(lambda: not window._services_busy))
        self.assertNotIn("disabled", window.api_start_button.state())
        # Un refresco pasivo ya no apaga el botón mientras lee…
        window._refresh_services()
        self.assertNotIn("disabled", window.api_start_button.state())
        # …y la orden que llega durante esa lectura se ejecuta al terminarla.
        window.api_port_var.set("8779")
        window._change_api(True)
        try:
            self.assertTrue(pump(lambda: window._services_snapshot.get("api", {}).get("running")),
                            "la API no llegó a iniciarse")
            # El resultado de «Probar acceso local» sobrevive al refresco automático.
            message = window._report_api_probe({"reachable": True, "status": 401}, False)
            window._refresh_services()
            self.assertTrue(pump(lambda: not window._services_busy))
            self.assertEqual(window.api_hint_var.get(), message)
        finally:
            self.runtime.api_server.stop()

    def test_refresh_does_not_fire_selection_events_when_nothing_changed(self) -> None:
        window = self.window
        fired = []
        window.topics_tree.bind("<<TreeviewSelect>>", lambda _event: fired.append(1), add="+")
        window._refresh_topics()
        first = window.topics_tree.get_children()[0]
        window.topics_tree.selection_set(first)
        window.update()
        fired.clear()
        window._replace_tree(window.topics_tree, [(row, window.topics_tree.item(row, "values"))
                                                  for row in window.topics_tree.get_children()])
        window.update()
        self.assertEqual(fired, [])


class ShortSourceSupportTests(unittest.TestCase):
    """Una fuente corta: la paráfrasis fiel tiene respaldo; lo que la fuente no dice, no."""

    SOURCE = ("# Cronología de Python 3.15\n\nPython 3.15 se publicó el 20 de octubre de 2026.\n\n"
              "La compilación por defecto de Python 3.15 es free-threaded, sin GIL.\n")

    def support(self, statement: str) -> str:
        from knowledge_orchestrator.services.semantic_maintenance.segmentos import find_support, source_segments

        sources = source_segments(self.SOURCE)
        return find_support(statement, self.SOURCE, sources, hinted=[sources[0].segment_id])[0]

    def test_faithful_paraphrase_of_a_short_source_is_supported(self) -> None:
        # Medido en real: antes quedaba como MODEL_LINKED y no proponía cambios.
        date = "**Python 3.15:** Fecha de publicación confirmada para el 20 de octubre de 2026."
        build = "**Compilación por defecto:** La versión 3.15 utilizará una compilación *free-threaded*."
        self.assertEqual(self.support(date), "SOURCE")
        self.assertEqual(self.support(build), "SOURCE")

    def test_claims_the_short_source_does_not_make_stay_unsupported(self) -> None:
        self.assertNotEqual(self.support("Python 3.15 se publicó el 25 de octubre de 2026."), "SOURCE")  # otra cifra
        self.assertNotEqual(self.support("El intérprete de Python 3.15 consume menos memoria y arranca más rápido "
                                         "gracias a la nueva caché."), "SOURCE")


class ProcessingTimeoutTests(RuntimeCase):
    """El perfil de fábrica falló con TASK_TIMEOUT a los 600 s con un documento de 690 bytes."""

    def test_factory_profile_and_requests_allow_large_local_models_to_load(self) -> None:
        from dataclasses import replace

        from knowledge_orchestrator.services.prompting import build_chat_request

        profile = self.runtime.profiles.list_profiles(enabled_only=True)[0]
        self.assertGreaterEqual(profile.consensus_timeout_seconds, 1800)
        for strategy in ("auto", "mixture_of_agents", "single"):
            request = build_chat_request(
                task_id="t", idempotency_key="k", workflow_id="w", step_id="single",
                profile=replace(profile, execution_strategy=strategy, multitasking_steps=("single", "synthesis")),
                system_content="Resume.", user_content="Texto.", execution_step="single")
            self.assertGreaterEqual(request["execution"]["timeout_seconds"], 1800, strategy)


class FailedDocumentExplanationTests(RuntimeCase):
    """Un documento que falla en el Broker lo cuenta en su línea de tiempo y en lenguaje llano."""

    def test_broker_failure_appears_in_the_document_timeline(self) -> None:
        self.paths.ensure_directories()
        source = self.paths.inbox / "doc.md"
        source.write_bytes(generic_markdown(capture_id="doc_timeout", title="Doc", transcript="Texto aportado."))
        self.assertTrue(self.runtime.ingestion.ingest(source).accepted)
        workflow_id = self.runtime.workflow_planner.plan_capture("doc_timeout")
        task = self.runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
        repository = self.runtime.workflow_repository
        self.assertIsNotNone(repository.claim_submission(task.task_id))
        repository.mark_accepted(task.task_id, {"status": "queued", "execution_strategy": "single",
                                                "execution_preset": "fast", "selection_mode": "auto",
                                                "task_id": "b1", "status_url": "/t/b1", "cancel_url": "/t/b1"})
        repository.apply_status(task.task_id, {"task_id": "b1", "status": "failed", "result": None, "error": {
            "code": "TASK_TIMEOUT", "message": "La tarea superó el timeout efectivo de 600 segundos.",
            "retryable": True}})
        events = [event.event_type for event in self.snapshots.work_events("doc_timeout")]
        self.assertIn("BROKER_TASK_FAILED", events)

    def test_local_only_document_can_be_retried_after_a_timeout(self) -> None:
        self.paths.ensure_directories()
        source = self.paths.inbox / "doc.md"
        source.write_bytes(generic_markdown(capture_id="doc_retry", title="Doc", transcript="Texto aportado."))
        self.assertTrue(self.runtime.ingestion.ingest(source).accepted)
        workflow_id = self.runtime.workflow_planner.plan_capture("doc_retry")
        repository = self.runtime.workflow_repository
        task = repository.list_workflow_tasks(workflow_id)[0]
        self.assertIsNotNone(repository.claim_submission(task.task_id))
        repository.mark_accepted(task.task_id, {"status": "queued", "execution_strategy": "single",
                                                "execution_preset": "fast", "selection_mode": "auto",
                                                "task_id": "b2", "status_url": "/t/b2", "cancel_url": "/t/b2"})
        repository.apply_status(task.task_id, {"task_id": "b2", "status": "failed", "result": None, "error": {
            "code": "TASK_TIMEOUT", "message": "plazo vencido", "retryable": True}})
        self.assertTrue(repository.retry_failed_task(task.task_id))
        self.assertIsNotNone(repository.claim_submission(task.task_id), "el reintento no puede agotar la bolsa")
        self.assertNotEqual(repository.get_task(task.task_id).error_code, "DOCUMENT_BUDGET_EXHAUSTED")


    def test_reused_identity_409_is_named_and_explained(self) -> None:
        import asyncio

        from knowledge_orchestrator.integrations.broker_client import PermanentBrokerError
        from knowledge_orchestrator.services.broker_submission import attempt_broker_submission
        from knowledge_orchestrator.ui.dashboard.base import provider_error_text

        class Client:
            async def create_task(self, _payload):
                raise PermanentBrokerError("Broker HTTP 409", status_code=409)

        decision = asyncio.run(attempt_broker_submission(Client(), "{}", attempt=1, backoff_seconds=()))
        self.assertEqual((decision.kind, decision.code), ("permanent", "IDEMPOTENCY_CONFLICT"))
        self.assertIn("Reintentar", provider_error_text("IDEMPOTENCY_CONFLICT", "Broker HTTP 409"))

    def test_timeout_is_explained_with_what_to_do(self) -> None:
        from knowledge_orchestrator.ui.dashboard.base import provider_error_text

        text = provider_error_text("TASK_TIMEOUT", "execution.timeout_seconds (600 s) … default_task_timeout_seconds")
        self.assertIn("Reintentar", text)
        self.assertNotIn("execution.timeout_seconds", text)


STUDY_NOTE = (
    "# Apunte\n\n"
    "## Ideas clave\n\n"
    "- La cartera reparte dividendos cada trimestre y reinvierte una parte.\n"
    "- El riesgo principal es la concentración sectorial de la cartera.\n"
)


class RetriedDocumentLifecycleTests(RuntimeCase):
    """Tras «Reintentar», el documento sigue su curso hasta el borrador o la publicación."""

    ACCEPTED = {"status": "queued", "execution_strategy": "single", "execution_preset": "fast",
                "selection_mode": "auto"}

    def prepare_failed(self, capture_id: str):
        from dataclasses import replace

        profile = self.runtime.profiles.list_profiles(enabled_only=True)[0]
        self.runtime.profiles.save_profile(replace(profile, human_review_required=True))
        self.paths.ensure_directories()
        source = self.paths.inbox / f"{capture_id}.md"
        source.write_bytes(generic_markdown(capture_id=capture_id, title="Doc", transcript="Texto aportado."))
        self.assertTrue(self.runtime.ingestion.ingest(source).accepted)
        workflow_id = self.runtime.workflow_planner.plan_capture(capture_id)
        repository = self.runtime.workflow_repository
        task = repository.list_workflow_tasks(workflow_id)[0]
        repository.claim_submission(task.task_id)
        broker = f"b_{capture_id}"
        repository.mark_accepted(task.task_id, {**self.ACCEPTED, "task_id": broker, "status_url": f"/t/{broker}",
                                                "cancel_url": f"/t/{broker}"})
        repository.apply_status(task.task_id, {"task_id": broker, "status": "failed", "result": None,
                                               "error": {"code": "TASK_TIMEOUT", "message": "plazo"}})
        return workflow_id, task

    def test_retried_document_reaches_draft_review(self) -> None:
        workflow_id, task = self.prepare_failed("doc_ciclo")
        repository = self.runtime.workflow_repository
        self.assertTrue(repository.retry_failed_task(task.task_id))
        self.assertIsNotNone(repository.claim_submission(task.task_id))
        repository.mark_accepted(task.task_id, {**self.ACCEPTED, "task_id": "c", "status_url": "/t/c",
                                                "cancel_url": "/t/c"})
        repository.apply_status(task.task_id, {"task_id": "c", "status": "processing", "result": None,
                                               "error": None})
        repository.apply_status(task.task_id, {"task_id": "c", "status": "success", "error": None, "result": {
            "assistant_content": STUDY_NOTE}})
        self.runtime.workflow_planner.advance_workflow(workflow_id)
        item = next(i for i in self.snapshots.work_items() if i.capture_id == "doc_ciclo")
        self.assertEqual(item.status, "AWAITING_REVIEW", (item.status, item.status_label))

    def test_migration_repairs_a_stuck_retry_but_not_a_reprocess_in_flight(self) -> None:
        from contextlib import closing

        workflow_id, task = self.prepare_failed("atascado")
        other_workflow, _ = self.prepare_failed("reproceso")
        with closing(self.runtime.database.connect()) as connection, connection:
            # Uno a medio «volver a procesar» tras descartar su borrador: no se toca.
            connection.execute("UPDATE captures SET status='PENDING' WHERE capture_id='reproceso'")
            connection.execute("UPDATE workflows SET status='SUCCESS', review_required=1, review_status='REJECTED', "
                               "final_result='# Viejo' WHERE workflow_id=?", (other_workflow,))
            # El estado exacto que dejaba el reintento antiguo al terminar el Broker.
            connection.execute("UPDATE captures SET status='PENDING' WHERE capture_id='atascado'")
            connection.execute("UPDATE workflows SET status='SUCCESS', review_required=1, review_status='PENDING', "
                               "final_result='# Apunte' WHERE workflow_id=?", (workflow_id,))
            sql = (Path(__file__).resolve().parents[1] / "src" / "knowledge_orchestrator" / "migrations"
                   / "026_retry_stuck_captures.sql").read_text(encoding="utf-8")
            connection.executescript(sql)
            states = dict(connection.execute(
                "SELECT capture_id, status FROM captures WHERE capture_id IN ('atascado','reproceso')").fetchall())
        self.assertEqual(states, {"atascado": "PROCESSING", "reproceso": "PENDING"})


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _text(widget) -> str:
    try:
        return str(widget.cget("text"))
    except tk.TclError:
        return ""


if __name__ == "__main__":
    unittest.main()
