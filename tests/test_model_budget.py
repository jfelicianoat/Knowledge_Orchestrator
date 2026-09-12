"""Modelos que razonan y presupuesto de respuesta (0.3.1).

Un documento real falló porque el modelo elegido gastó los 1200 tokens
razonando y nunca escribió la respuesta. Lo que se fija aquí: qué modelos se
ofrecen, cómo se amplía el presupuesto sin intervención y qué lee la persona.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.repositories.workflow_repository.estado import (
    BUDGET_CEILING,
    ampliar_presupuesto,
    presupuesto_agotado,
)
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.model_selection import choose_json_model, json_model_from_catalog
from knowledge_orchestrator.services.semantic_maintenance.prompts import TASK_BUDGETS, PromptsMixin
from knowledge_orchestrator.ui.dashboard.base import provider_error_text
from knowledge_orchestrator.ui.snapshots import UiSnapshotService
from tests.helpers import generic_markdown

LENGTH_ERROR = ("Ollama no devolvió message.content (done_reason=length, eval_count=1200, "
                "thinking=5290 caracteres; el razonamiento agotó max_output_tokens antes de responder)")


class CatalogTests(unittest.TestCase):
    """Capa 1: no ofrecer lo que el Broker ya sabe que no sirve."""

    def test_incompatible_and_quarantined_models_are_not_offered(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            runtime = build_runtime(PipelinePaths.under(Path(folder)))
            runtime.workflow_repository.upsert_models([
                {"name": "gemma4:12b", "provider": "ollama", "status": "available", "context_window": 262144,
                 "capabilities": ["completion", "tools", "thinking"], "compatibility": "compatible",
                 "quarantined": False},
                {"name": "roto", "provider": "lmstudio", "status": "online", "context_window": 32768,
                 "capabilities": ["completion"], "compatibility": "incompatible", "quarantined": False},
                {"name": "en-cuarentena", "provider": "ollama", "status": "available", "context_window": 8192,
                 "capabilities": ["completion"], "compatibility": "compatible", "quarantined": True},
                {"name": "llano", "provider": "ollama", "status": "available", "context_window": 8192,
                 "capabilities": ["completion"], "compatibility": "compatible", "quarantined": False},
            ], "2026-09-12T08:00:00Z")
            options = UiSnapshotService(runtime.database).models()

        self.assertEqual([option.name for option in options], ["gemma4:12b", "llano"])
        thinking = next(option for option in options if option.name == "gemma4:12b")
        plain = next(option for option in options if option.name == "llano")
        self.assertTrue(thinking.thinking)
        self.assertFalse(plain.thinking)
        self.assertIn("razona", thinking.label)
        self.assertNotIn("razona", plain.label)
        self.assertIn("262k contexto", thinking.label)


class BudgetTests(unittest.TestCase):
    """Capa 2: el presupuesto agotado se reconoce y se amplía una vez."""

    def test_only_an_exhausted_budget_is_treated_as_such(self) -> None:
        self.assertTrue(presupuesto_agotado({"code": "INVALID_PROVIDER_RESPONSE", "message": LENGTH_ERROR}))
        self.assertFalse(presupuesto_agotado({"code": "MODEL_UNAVAILABLE", "message": LENGTH_ERROR}))
        self.assertFalse(presupuesto_agotado(
            {"code": "INVALID_PROVIDER_RESPONSE", "message": "El proveedor devolvió JSON inválido"}))

    def test_budget_doubles_up_to_the_ceiling(self) -> None:
        request = {"generation": {"temperature": 0.0, "max_output_tokens": 4000}}
        self.assertEqual(ampliar_presupuesto(request)["generation"]["max_output_tokens"], 8000)
        self.assertEqual(request["generation"]["max_output_tokens"], 4000, "no debe mutar la petición original")
        self.assertEqual(
            ampliar_presupuesto({"generation": {"max_output_tokens": BUDGET_CEILING - 1}})
            ["generation"]["max_output_tokens"], BUDGET_CEILING)
        self.assertIsNone(ampliar_presupuesto({"generation": {"max_output_tokens": BUDGET_CEILING}}))
        self.assertIsNone(ampliar_presupuesto({"generation": {}}))

    def test_the_task_is_reopened_once_with_a_new_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            paths = PipelinePaths.under(Path(folder))
            runtime = build_runtime(paths)
            source = paths.inbox / "presupuesto.md"
            source.write_bytes(generic_markdown(capture_id="presupuesto", title="Documento de presupuesto"))
            self.assertTrue(runtime.ingestion.ingest(source).accepted)
            workflow_id = runtime.workflow_planner.plan_capture("presupuesto")
            repository = runtime.workflow_repository
            task = repository.list_workflow_tasks(workflow_id)[0]
            original_key = task.idempotency_key
            budget = json.loads(task.request_json)["generation"]["max_output_tokens"]
            failure = {"task_id": task.task_id, "status": "failed", "result": None,
                       "error": {"code": "INVALID_PROVIDER_RESPONSE", "message": LENGTH_ERROR, "retryable": True}}

            self.assertTrue(repository.apply_status(task.task_id, failure))

            reopened = repository.get_task(task.task_id)
            self.assertEqual(reopened.status.value, "READY")
            self.assertEqual(json.loads(reopened.request_json)["generation"]["max_output_tokens"], budget * 2)
            self.assertNotEqual(reopened.idempotency_key, original_key)
            # La captura no cae a FALLIDO: nadie tiene que rescatarla a mano.
            self.assertIn(runtime.repository.get("presupuesto").status.value,
                          {"PENDING", "SUBMITTING", "QUEUED", "PROCESSING"})
            with closing(runtime.database.connect(readonly=True)) as connection:
                events = [row["event_type"] for row in connection.execute(
                    "SELECT event_type FROM events WHERE capture_id = 'presupuesto'")]
            self.assertIn("BROKER_BUDGET_RETRY", events)

            # Segunda vez con el mismo fallo: ya no se amplía sola, decide una persona.
            self.assertTrue(repository.apply_status(reopened.task_id, failure))
            final = repository.get_task(task.task_id)
            self.assertEqual(final.status.value, "ERROR")
            self.assertEqual(final.error_code, "INVALID_PROVIDER_RESPONSE")


class RetryPolicyTests(unittest.TestCase):
    """Reintentar usa la configuración de ahora, no la que ya falló."""

    def test_retry_resends_with_the_current_model_and_budget(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            paths = PipelinePaths.under(Path(folder))
            runtime = build_runtime(paths)
            source = paths.inbox / "politica.md"
            source.write_bytes(generic_markdown(capture_id="politica", title="Documento de política"))
            self.assertTrue(runtime.ingestion.ingest(source).accepted)
            workflow_id = runtime.workflow_planner.plan_capture("politica")
            repository = runtime.workflow_repository
            task = repository.list_workflow_tasks(workflow_id)[0]
            with closing(runtime.database.connect(readonly=True)) as connection:
                profile_id = connection.execute(
                    "SELECT profile_id FROM workflows WHERE workflow_id = ?", (workflow_id,)).fetchone()[0]
            # La persona cambia el modelo en Ajustes tras ver el fallo.
            profile = runtime.profiles.get_profile(profile_id)
            runtime.profiles.save_profile(replace(profile, preferred_model="gemma4:12b", max_output_tokens=9000))
            repository.apply_status(task.task_id, {
                "task_id": task.task_id, "status": "failed", "result": None,
                "error": {"code": "MODEL_UNAVAILABLE", "message": "Modelo no disponible", "retryable": True}})

            self.assertTrue(repository.retry_failed_task(task.task_id))

            resent = json.loads(repository.get_task(task.task_id).request_json)
            self.assertEqual(resent["model_requirements"]["preferred_model"], "gemma4:12b")
            self.assertEqual(resent["generation"]["max_output_tokens"], 9000)


class ModelSubstitutionTests(unittest.TestCase):
    """El modelo elegido viaja como exigencia cuando se pide que no haya sustitución."""

    def test_the_request_forbids_substitution_when_the_profile_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            paths = PipelinePaths.under(Path(folder))
            runtime = build_runtime(paths)
            source = paths.inbox / "sustitucion.md"
            source.write_bytes(generic_markdown(capture_id="sustitucion", title="Documento sin sustitución"))
            self.assertTrue(runtime.ingestion.ingest(source).accepted)
            with closing(runtime.database.connect(readonly=True)) as connection:
                profile_id = connection.execute(
                    "SELECT profile_id FROM profiles WHERE name = 'Técnico Profundo'").fetchone()[0]
            profile = runtime.profiles.get_profile(profile_id)
            runtime.profiles.save_profile(
                replace(profile, preferred_model="gemma4:12b", fallback_allowed=False))
            workflow_id = runtime.workflow_planner.plan_capture("sustitucion")
            task = runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]

            request = json.loads(task.request_json)

            self.assertEqual(request["model_requirements"]["preferred_model"], "gemma4:12b")
            self.assertFalse(request["model_requirements"]["fallback_allowed"])
            self.assertFalse(request["execution"]["selection"]["allow_substitution"])


class SemanticBudgetTests(unittest.TestCase):
    """Capa 3: cada tipo de tarea semántica lleva su presupuesto, no una constante."""

    def test_every_semantic_task_declares_its_own_budget(self) -> None:
        self.assertEqual(set(TASK_BUDGETS), {"extraction", "comparison", "embedding", "query"})
        schema = {"type": "object", "additionalProperties": False, "required": ["ok"],
                  "properties": {"ok": {"type": "boolean"}}}
        request = PromptsMixin.broker_json_request(
            request_id="semantic_extract_note_1", prompt="hola", schema=schema,
            max_output_tokens=TASK_BUDGETS["comparison"])
        self.assertEqual(request["generation"]["max_output_tokens"], TASK_BUDGETS["comparison"])
        self.assertEqual(
            PromptsMixin.embedding_request(1, "afirmación")["generation"]["max_output_tokens"],
            TASK_BUDGETS["embedding"])


class JsonModelChoiceTests(unittest.TestCase):
    """Las tareas con esquema evitan los modelos que razonan."""

    CATALOG = [
        {"name": "a-razonador", "provider": "ollama",
         "capabilities_json": json.dumps({"capabilities": ["completion", "thinking"],
                                          "compatibility": "compatible", "quarantined": False})},
        {"name": "b-incompatible", "provider": "ollama",
         "capabilities_json": json.dumps({"capabilities": ["completion"],
                                          "compatibility": "incompatible", "quarantined": False})},
        {"name": "c-en-cuarentena", "provider": "ollama",
         "capabilities_json": json.dumps({"capabilities": ["completion"],
                                          "compatibility": "compatible", "quarantined": True})},
        {"name": "d-otro-proveedor", "provider": "lmstudio",
         "capabilities_json": json.dumps({"capabilities": ["completion"],
                                          "compatibility": "compatible", "quarantined": False})},
        {"name": "e-valido", "provider": "ollama",
         "capabilities_json": json.dumps({"capabilities": ["completion", "tools"],
                                          "compatibility": "compatible", "quarantined": False})},
    ]

    def test_the_first_usable_model_without_reasoning_is_chosen(self) -> None:
        self.assertEqual(choose_json_model(self.CATALOG), "e-valido")

    def test_without_candidates_the_broker_decides(self) -> None:
        self.assertIsNone(choose_json_model(self.CATALOG[:4]))
        self.assertIsNone(choose_json_model([]))

    def test_specialised_and_oversized_models_are_not_chosen(self) -> None:
        """El primer criterio eligió un OCR de 1.1B por ir primero en el alfabeto."""

        catalog = [
            {"name": "glm-ocr:latest", "provider": "ollama",
             "capabilities_json": json.dumps({"capabilities": ["vision", "completion", "tools"],
                                              "family": "glmocr", "parameter_size": "1.1B"})},
            {"name": "qwen3-coder:30b", "provider": "ollama",
             "capabilities_json": json.dumps({"capabilities": ["completion", "tools"],
                                              "family": "qwen3moe", "parameter_size": "30.5B"})},
            {"name": "nemotron:latest", "provider": "ollama",
             "capabilities_json": json.dumps({"capabilities": ["completion", "tools"],
                                              "family": "llama", "parameter_size": "70.6B"})},
            {"name": "granite4.1:30b", "provider": "ollama",
             "capabilities_json": json.dumps({"capabilities": ["completion", "tools"],
                                              "family": "granite", "parameter_size": "28.9B"})},
            {"name": "lfm2:24b", "provider": "ollama",
             "capabilities_json": json.dumps({"capabilities": ["completion", "tools"],
                                              "family": "lfm2moe", "parameter_size": "23.8B"})},
        ]

        self.assertEqual(choose_json_model(catalog), "granite4.1:30b")

    def test_the_semantic_request_carries_that_model(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            runtime = build_runtime(PipelinePaths.under(Path(folder)))
            runtime.workflow_repository.upsert_models([
                {"name": "gemma4:12b", "provider": "ollama", "status": "available", "context_window": 262144,
                 "capabilities": ["completion", "thinking"], "compatibility": "compatible", "quarantined": False},
                {"name": "llama-instruct", "provider": "ollama", "status": "available", "context_window": 8192,
                 "capabilities": ["completion"], "compatibility": "compatible", "quarantined": False},
            ], "2026-09-12T09:00:00Z")

            chosen = json_model_from_catalog(runtime.database)
            request = PromptsMixin.broker_json_request(
                request_id="semantic_extract_note_1", prompt="hola",
                schema={"type": "object", "additionalProperties": False, "required": ["ok"],
                        "properties": {"ok": {"type": "boolean"}}},
                preferred_model=chosen)

        self.assertEqual(chosen, "llama-instruct")
        self.assertEqual(request["model_requirements"]["preferred_model"], "llama-instruct")


class SemanticIdempotencyTests(unittest.TestCase):
    """Reintentar con otra configuración no debe chocar con el 409 del Broker."""

    SCHEMA = {"type": "object", "additionalProperties": False, "required": ["ok"],
              "properties": {"ok": {"type": "boolean"}}}

    def key(self, **changes) -> str:
        arguments = {"request_id": "semantic_extract_note_1", "prompt": "documento", "schema": self.SCHEMA,
                     "preferred_model": "granite4.1:30b", "max_output_tokens": 6000}
        return PromptsMixin.broker_json_request(**{**arguments, **changes})["idempotency_key"]

    def test_same_content_keeps_the_key_and_different_content_changes_it(self) -> None:
        original = self.key()
        self.assertTrue(original.startswith("semantic_extract_note_1:"))
        self.assertEqual(original, self.key(), "el replay idempotente debe conservar la clave")
        self.assertNotEqual(original, self.key(preferred_model="lfm2:24b"))
        self.assertNotEqual(original, self.key(max_output_tokens=12000))
        self.assertNotEqual(original, self.key(prompt="otro documento"))


class ProviderMessageTests(unittest.TestCase):
    """Capa 4: el fallo se lee y dice qué hacer."""

    def test_the_budget_failure_is_explained_without_jargon(self) -> None:
        text = provider_error_text("INVALID_PROVIDER_RESPONSE", LENGTH_ERROR)
        self.assertIn("agotó su presupuesto", text)
        self.assertIn("Ajustes", text)
        self.assertNotIn("done_reason", text)
        other = provider_error_text("MODEL_UNAVAILABLE", "Modelo no disponible")
        self.assertEqual(other, "Modelo no disponible")


if __name__ == "__main__":
    unittest.main()
