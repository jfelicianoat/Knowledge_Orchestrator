"""Regresiones de la incidencia del 26-oct-2026: documentos rechazados por coste con modelos gratuitos.

Siete documentos con perfil `public` murieron con DOCUMENT_BUDGET_EXHAUSTED al
reintentarlos, aunque el Broker solo tenía modelos gratuitos y nunca cobró nada.
Tres caminos llevaban a lo mismo: la reserva del intento fallido no volvía a la
bolsa del documento y el reintento pedía otra vez el tope entero.
"""
from __future__ import annotations

import json
from contextlib import closing

from knowledge_orchestrator.domain.broker_models import TaskStatus
from knowledge_orchestrator.repositories.workflow_repository.estado import coste_liquidable
from tests.test_audit_2026_09_27 import ACCEPTED, AuditBase

LENGTH_ERROR = "El proveedor devolvió una respuesta vacía (done_reason=length)."


class CosteInformadoAlFallarTests(AuditBase):
    """El Broker cuenta el coste en `progress.cost_actual_usd` también cuando la tarea falla."""

    def enviar_y_fallar(self, capture_id: str, error: dict, progress: dict | None, *, cloud: bool = True) -> str:
        # Con nube, para que la reserva prudente tenga sentido: sin nube no cuesta nada.
        self.profile(max_cost_usd=0.05, data_classification="public", cloud_allowed=cloud)
        self.ingest(capture_id, "Texto breve.")
        workflow_id = self.runtime.workflow_planner.plan_capture(capture_id)
        repository = self.runtime.workflow_repository
        task = repository.list_workflow_tasks(workflow_id)[0]
        self.assertIsNotNone(repository.claim_submission(task.task_id))
        repository.mark_accepted(task.task_id, {**ACCEPTED, "task_id": capture_id, "status_url": "/t/x",
                                                "cancel_url": "/t/x"})
        payload = {"task_id": capture_id, "status": "failed", "result": None, "error": error}
        if progress is not None:
            payload["progress"] = progress
        repository.apply_status(task.task_id, payload)
        return task.task_id

    def test_timeout_con_coste_cero_informado_permite_reintentar(self) -> None:
        # El caso real: TASK_TIMEOUT con modelos gratuitos y perfil público.
        task_id = self.enviar_y_fallar(
            "gratis", {"code": "TASK_TIMEOUT", "message": "plazo vencido", "retryable": True},
            {"budget_limit_usd": 0.05, "cost_actual_usd": 0.0},
        )
        repository = self.runtime.workflow_repository
        self.assertTrue(repository.retry_failed_task(task_id))
        self.assertIsNotNone(repository.claim_submission(task_id), "el reintento no puede agotar la bolsa")
        self.assertNotEqual(repository.get_task(task_id).error_code, "DOCUMENT_BUDGET_EXHAUSTED")

    def test_timeout_sin_coste_con_nube_permite_reintentar(self) -> None:
        # 27-oct: el coste lo controla el Broker; KO ya no bloquea el reintento por su bolsa.
        task_id = self.enviar_y_fallar(
            "con_nube", {"code": "TASK_TIMEOUT", "message": "plazo vencido", "retryable": True}, None,
        )
        repository = self.runtime.workflow_repository
        self.assertTrue(repository.retry_failed_task(task_id))
        self.assertIsNotNone(repository.claim_submission(task_id))

    def test_timeout_sin_coste_y_sin_nube_permite_reintentar(self) -> None:
        # Incidencia real 27-oct: perfil `public` con solo ollama; el Broker no informa coste en TASK_TIMEOUT.
        task_id = self.enviar_y_fallar(
            "sin_nube", {"code": "TASK_TIMEOUT", "message": "plazo vencido", "retryable": True}, None, cloud=False,
        )
        repository = self.runtime.workflow_repository
        self.assertTrue(repository.retry_failed_task(task_id))
        self.assertIsNotNone(repository.claim_submission(task_id), "sin nube no hay nada que cobrar")

    def test_perfil_con_nube_pide_sus_proveedores_y_reserva(self) -> None:
        # Proveedores configurables desde Ajustes (27-oct): la petición lleva los del perfil y la nube abierta.
        self.profile(max_cost_usd=0.05, data_classification="public", cloud_allowed=True,
                     allowed_providers=("ollama", "FreeLLMapi"))
        self.ingest("nube", "Texto breve.")
        workflow_id = self.runtime.workflow_planner.plan_capture("nube")
        repository = self.runtime.workflow_repository
        task = repository.list_workflow_tasks(workflow_id)[0]
        requisitos = json.loads(task.request_json)["model_requirements"]
        self.assertEqual(requisitos["allowed_providers"], ["ollama", "FreeLLMapi"])
        self.assertNotEqual(requisitos.get("cloud_allowed"), False)
        self.assertIsNotNone(repository.claim_submission(task.task_id))
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            reservado = connection.execute(
                "SELECT budget_reserved_usd FROM tasks WHERE task_id = ?", (task.task_id,)
            ).fetchone()[0]
        self.assertAlmostEqual(reservado, 0.05)

    def test_coste_de_pago_informado_se_queda_en_la_bolsa(self) -> None:
        task_id = self.enviar_y_fallar(
            "pago", {"code": "TASK_TIMEOUT", "message": "plazo vencido", "retryable": True},
            {"cost_actual_usd": 0.02},
        )
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            reservado = connection.execute(
                "SELECT budget_reserved_usd FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()[0]
        self.assertAlmostEqual(reservado, 0.02)

    def test_el_resultado_manda_sobre_el_progreso(self) -> None:
        coste = coste_liquidable(TaskStatus.SUCCESS, {"usage": {"cost_usd": 0.01}}, {}, {"cost_actual_usd": 0.0})
        self.assertEqual(coste, 0.01)

    def test_reintento_automatico_por_tokens_liquida_el_intento_cortado(self) -> None:
        task_id = self.enviar_y_fallar(
            "tokens", {"code": "INVALID_PROVIDER_RESPONSE", "message": LENGTH_ERROR, "retryable": True},
            {"cost_actual_usd": 0.0},
        )
        repository = self.runtime.workflow_repository
        self.assertEqual(repository.get_task(task_id).status, TaskStatus.READY)
        self.assertIsNotNone(repository.claim_submission(task_id), "el reenvío ampliado no puede agotar la bolsa")


class ReintentoDeDocumentoTests(AuditBase):
    """«Reintentar» no reabre a la vez una tarea y la alternativa que ya la sustituyó."""

    def test_solo_se_reabre_la_alternativa(self) -> None:
        self.profile(execution_strategy="auto", multitasking_steps=("single", "synthesis"),
                     consensus_fallback_to_single=True, max_cost_usd=0.05, data_classification="public")
        self.ingest("alternativa", "Texto breve.")
        workflow_id = self.runtime.workflow_planner.plan_capture("alternativa")
        repository = self.runtime.workflow_repository
        original = repository.list_workflow_tasks(workflow_id)[0]
        repository.claim_submission(original.task_id)
        repository.mark_accepted(original.task_id, {**ACCEPTED, "execution_strategy": "auto", "task_id": "o",
                                                    "status_url": "/t/o", "cancel_url": "/t/o"})
        repository.apply_status(original.task_id, {"task_id": "o", "status": "failed", "result": None,
                                                   "error": {"code": "CONSENSUS_QUORUM_NOT_REACHED", "message": "q"}})
        self.runtime.workflow_planner.advance_workflow(workflow_id)
        fallback = next(item for item in repository.list_workflow_tasks(workflow_id)
                        if item.replacement_for_task_id == original.task_id)
        repository.claim_submission(fallback.task_id)
        repository.mark_accepted(fallback.task_id, {**ACCEPTED, "task_id": "f", "status_url": "/t/f",
                                                    "cancel_url": "/t/f"})
        repository.apply_status(fallback.task_id, {"task_id": "f", "status": "failed", "result": None,
                                                   "error": {"code": "MODEL_UNAVAILABLE", "message": "no"}})

        self.assertEqual(repository.retry_failed_capture("alternativa"), [fallback.task_id])
        self.assertEqual(repository.get_task(original.task_id).status, TaskStatus.ERROR)
        self.assertIsNotNone(repository.claim_submission(fallback.task_id))
        # Incidencia real 27-oct: la alternativa reintentada repetía la clave de la original → HTTP 409.
        self.assertTrue(repository.get_task(fallback.task_id).idempotency_key.endswith(":fallback:manual-2"))

    def test_alternativa_de_una_original_reintentada_no_repite_su_clave(self) -> None:
        self.profile(execution_strategy="auto", multitasking_steps=("single", "synthesis"),
                     consensus_fallback_to_single=True)
        self.ingest("clave", "Texto breve.")
        workflow_id = self.runtime.workflow_planner.plan_capture("clave")
        repository = self.runtime.workflow_repository
        original = repository.list_workflow_tasks(workflow_id)[0]
        with self.runtime.database.transaction(immediate=True) as connection:
            # La original ya llevaba un reintento manual cuando nació la alternativa (caso real).
            connection.execute("UPDATE tasks SET idempotency_key = idempotency_key || ':manual-2' "
                               "WHERE task_id = ?", (original.task_id,))
        repository.claim_submission(original.task_id)
        repository.mark_accepted(original.task_id, {**ACCEPTED, "execution_strategy": "auto", "task_id": "o",
                                                    "status_url": "/t/o", "cancel_url": "/t/o"})
        repository.apply_status(original.task_id, {"task_id": "o", "status": "failed", "result": None,
                                                   "error": {"code": "CONSENSUS_QUORUM_NOT_REACHED", "message": "q"}})
        self.runtime.workflow_planner.advance_workflow(workflow_id)
        fallback = next(item for item in repository.list_workflow_tasks(workflow_id)
                        if item.replacement_for_task_id == original.task_id)
        repository.claim_submission(fallback.task_id)
        repository.mark_accepted(fallback.task_id, {**ACCEPTED, "task_id": "f", "status_url": "/t/f",
                                                    "cancel_url": "/t/f"})
        repository.apply_status(fallback.task_id, {"task_id": "f", "status": "failed", "result": None,
                                                   "error": {"code": "MODEL_UNAVAILABLE", "message": "no"}})
        self.assertTrue(repository.retry_failed_task(fallback.task_id))
        claves = {repository.get_task(original.task_id).idempotency_key,
                  repository.get_task(fallback.task_id).idempotency_key}
        self.assertEqual(len(claves), 2, claves)
