"""Quién elige el modelo de análisis y quién cuenta los caracteres (0.3.3).

Contra el Broker real, dos modelos distintos extrajeron las afirmaciones
correctas del documento y las acompañaron de spans inventados: tramos
consecutivos —(0,79), (80,119), (120,169)— que no correspondían a nada. Contar
caracteres no es algo que un modelo pueda hacer, así que localizar la cita pasó
a ser trabajo de la aplicación. Lo que se fija aquí: que la garantía
anti-invención siga intacta, que la elección de la persona manda y que un modelo
que ya falló no vuelve a proponerse solo.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.model_selection import (
    choose_json_model,
    json_model_from_catalog,
    pinned_analysis_model,
    record_analysis_failure,
)
from knowledge_orchestrator.services.semantic_maintenance.analisis import AnalisisMixin, locate_quote

#: Lo que de verdad respondió `lfm2:24b`: la cita une los renglones con un
#: espacio donde el documento tiene un salto de línea.
DOCUMENT = (
    "# Publicación atómica\n\n"
    "Knowledge Orchestrator escribe primero un archivo temporal sincronizado en la misma unidad y\n"
    "reemplaza después el destino con os.replace, que es atómico en NTFS.\n"
)
MODEL_QUOTE = ("Knowledge Orchestrator escribe primero un archivo temporal sincronizado en la misma unidad y "
               "reemplaza después el destino con os.replace, que es atómico en NTFS.")


def _claim(**overrides: object) -> dict:
    claim = {"statement": MODEL_QUOTE, "claim_type": "process", "volatility": "LOW",
             "quote": MODEL_QUOTE, "entities": ["Knowledge Orchestrator"]}
    claim.update(overrides)
    return claim


class SpanLocationTests(unittest.TestCase):
    """La aplicación localiza la cita; el modelo solo tiene que copiarla."""

    def test_a_quote_whose_line_break_became_a_space_is_located(self) -> None:
        located = locate_quote(DOCUMENT, MODEL_QUOTE, body_start=0)
        self.assertIsNotNone(located)
        assert located is not None
        start, end = located
        self.assertEqual(DOCUMENT[start:end], MODEL_QUOTE.replace("unidad y ", "unidad y\n"))

    def test_invented_spans_do_not_prevent_the_extraction(self) -> None:
        """El caso real: contenido correcto, offsets inventados."""

        claims = AnalisisMixin._parse_extraction(
            {"claims": [_claim(span_start=0, span_end=79)]}, DOCUMENT
        )

        self.assertEqual(len(claims), 1)
        # La evidencia guardada es el texto del documento, no la versión del modelo.
        self.assertEqual(DOCUMENT[claims[0].span_start:claims[0].span_end], claims[0].quote)
        self.assertEqual(claims[0].statement, claims[0].quote)

    def test_a_quote_that_is_not_in_the_document_is_still_rejected(self) -> None:
        with self.assertRaises(Exception) as error:
            AnalisisMixin._parse_extraction(
                {"claims": [_claim(statement="El sistema usa PostgreSQL", quote="El sistema usa PostgreSQL")]},
                DOCUMENT,
            )
        self.assertIn("no está respaldado", str(error.exception))

    def test_correct_spans_are_respected_so_a_repeated_quote_keeps_its_place(self) -> None:
        """Con dos ocurrencias iguales, un span correcto distingue cuál es."""

        document = "# Doc\n\nProducto X versión 1.\n\nProducto X versión 1.\n"
        second = document.rindex("Producto X versión 1.")
        claims = AnalisisMixin._parse_extraction(
            {"claims": [{"statement": "Producto X versión 1.", "claim_type": "VERSION", "volatility": "LOW",
                         "span_start": second, "span_end": second + len("Producto X versión 1."),
                         "quote": "Producto X versión 1.", "entities": []}]},
            document,
        )

        self.assertEqual(claims[0].span_start, second)


class AnalysisModelChoiceTests(unittest.TestCase):
    """Capa de control: la persona decide y la aplicación recuerda los fracasos."""

    CATALOG = [
        {"name": "modelo-a", "provider": "ollama",
         "capabilities_json": json.dumps({"capabilities": ["completion", "tools"], "parameter_size": "24B"})},
        {"name": "modelo-b", "provider": "ollama",
         "capabilities_json": json.dumps({"capabilities": ["completion", "tools"], "parameter_size": "12B"})},
    ]

    def test_a_model_that_failed_is_not_proposed_again(self) -> None:
        self.assertEqual(choose_json_model(self.CATALOG), "modelo-a")
        self.assertEqual(choose_json_model(self.CATALOG, rejected=["modelo-a"]), "modelo-b")
        self.assertIsNone(choose_json_model(self.CATALOG, rejected=["modelo-a", "modelo-b"]))

    def test_the_chosen_model_wins_over_the_automatic_one(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            runtime = build_runtime(PipelinePaths.under(Path(folder)))
            runtime.workflow_repository.upsert_models([
                {"name": "llama-instruct", "provider": "ollama", "status": "available", "context_window": 8192,
                 "capabilities": ["completion"], "compatibility": "compatible", "quarantined": False},
            ], "2026-09-13T09:00:00Z")
            self.assertEqual(json_model_from_catalog(runtime.database), "llama-instruct")

            profile = runtime.profiles.list_profiles()[0]
            runtime.profiles.save_profile(replace(profile, analysis_model="lfm2:24b"))
            pinned = pinned_analysis_model(runtime.database, profile_id=profile.profile_id)

            self.assertEqual(pinned, "lfm2:24b")
            self.assertEqual(json_model_from_catalog(runtime.database, chosen=pinned), "lfm2:24b")

    def test_a_failed_extraction_excludes_the_model_from_the_automatic_choice(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            runtime = build_runtime(PipelinePaths.under(Path(folder)))
            runtime.workflow_repository.upsert_models([
                {"name": "llama-instruct", "provider": "ollama", "status": "available", "context_window": 8192,
                 "capabilities": ["completion"], "compatibility": "compatible", "quarantined": False},
            ], "2026-09-13T09:00:00Z")

            record_analysis_failure(runtime.database, "llama-instruct", "SEMANTIC_CONTRACT_FAILED", "bucle")
            record_analysis_failure(runtime.database, "llama-instruct", "SEMANTIC_CONTRACT_FAILED", "bucle otra vez")

            self.assertIsNone(json_model_from_catalog(runtime.database))
            with closing(runtime.database.connect(readonly=True)) as connection:
                row = connection.execute(
                    "SELECT failures, message FROM analysis_model_failures WHERE model = 'llama-instruct'"
                ).fetchone()
            self.assertEqual(row["failures"], 2)
            self.assertEqual(row["message"], "bucle otra vez")


if __name__ == "__main__":
    unittest.main()
