"""Regresiones del 25-oct-2026: documentos en «Necesitan atención» que no se podían reenviar.

En un documento troceado la última tarea suele ser un fragmento que salió bien:
el botón «Reintentar» quedaba apagado y, de haberse pulsado, habría reintentado
ese fragmento y no el que falló.
"""
from __future__ import annotations

from contextlib import closing

from knowledge_orchestrator.ui.dashboard.trabajo_detalle import DetalleMixin
from tests.helpers import generic_markdown
from tests.test_uso_real_2026_10_08 import RuntimeCase

ACCEPTED = {"status": "queued", "execution_strategy": "single", "execution_preset": "fast", "selection_mode": "auto"}


class ResendFailedDocumentTests(RuntimeCase):
    def chunked_document(self, capture_id: str, error_code: str):
        self.paths.ensure_directories()
        source = self.paths.inbox / f"{capture_id}.md"
        source.write_bytes(generic_markdown(capture_id=capture_id, title="Doc", transcript="dato técnico " * 5000))
        self.assertTrue(self.runtime.ingestion.ingest(source).accepted)
        workflow_id = self.runtime.workflow_planner.plan_capture(capture_id)
        repository = self.runtime.workflow_repository
        first, second = repository.list_workflow_tasks(workflow_id)[:2]
        for task in (first, second):
            repository.claim_submission(task.task_id)
            repository.mark_accepted(task.task_id, {**ACCEPTED, "task_id": f"b_{task.task_id}",
                                                    "status_url": "/t", "cancel_url": "/t"})
        repository.apply_status(first.task_id, {"task_id": f"b_{first.task_id}", "status": "failed", "result": None,
                                                "error": {"code": error_code, "message": "fallo"}})
        # El fragmento siguiente termina bien DESPUÉS: pasa a ser la última tarea.
        repository.apply_status(second.task_id, {"task_id": f"b_{second.task_id}", "status": "success",
                                                 "error": None, "result": {"assistant_content": "# Parte"}})
        with closing(self.runtime.database.connect()) as connection, connection:
            connection.execute("UPDATE tasks SET updated_at = '2999-01-01T00:00:00.000Z' WHERE task_id = ?",
                               (second.task_id,))
        item = next(i for i in self.snapshots.work_items() if i.capture_id == capture_id)
        self.assertEqual((item.category, item.task_id), ("attention", second.task_id))
        return workflow_id, first

    def test_failed_fragment_is_resent_even_if_the_last_task_succeeded(self) -> None:
        workflow_id, failed = self.chunked_document("troceado", "MODEL_ERROR")
        item = next(i for i in self.snapshots.work_items() if i.capture_id == "troceado")
        self.assertTrue(DetalleMixin._can_send_item(item), "el botón quedaba apagado")

        self.assertEqual(self.runtime.workflow_repository.retry_failed_capture("troceado"), [failed.task_id])
        dispatchable = [t.task_id for t in self.runtime.workflow_repository.list_dispatchable()]
        self.assertIn(failed.task_id, dispatchable)
        item = next(i for i in self.snapshots.work_items() if i.capture_id == "troceado")
        self.assertNotEqual(item.category, "attention")

    def test_prompt_rejected_as_image_request_is_replanned_not_repeated(self) -> None:
        self.chunked_document("imagen", "IMAGE_GENERATION_UNSUPPORTED")
        self.assertEqual(self.runtime.workflow_repository.retry_failed_capture("imagen"), [])
        with closing(self.runtime.database.connect()) as connection:
            status = connection.execute("SELECT status FROM captures WHERE capture_id='imagen'").fetchone()[0]
        self.assertEqual(status, "PENDING", "debe volver a planificarse con el prompt actual")

    def test_nothing_to_resend_returns_none(self) -> None:
        self.assertIsNone(self.runtime.workflow_repository.retry_failed_capture("no_existe"))
