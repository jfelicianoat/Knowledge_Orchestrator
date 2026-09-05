from __future__ import annotations

import unittest

from knowledge_orchestrator.services.output_quality import study_notes_quality_error


class StudyNotesOutputQualityTests(unittest.TestCase):
    def test_rejects_answer_that_asks_the_user_for_instructions(self) -> None:
        answer = (
            "It looks like you shared a transcript, but there is no specific request. "
            "What would you like me to do?"
        )
        self.assertEqual(study_notes_quality_error(answer, final=True), "MISSING_EXECUTION")

    def test_rejects_english_final_answer_and_obvious_cutoff(self) -> None:
        english = "The transcript explains the system and how the user can configure it for their own workflow. " * 20
        self.assertEqual(study_notes_quality_error(english, final=True), "WRONG_LANGUAGE")
        truncated = (
            "# Título\n\n## Resumen ejecutivo\nBien.\n\n## Desarrollo\n"
            + "Contenido explicado con detalle suficiente para ocupar la respuesta. " * 12
            + "\n\n### Parte incompleta"
        )
        self.assertEqual(study_notes_quality_error(truncated, final=True), "TRUNCATED_OUTPUT")

    def test_accepts_a_structured_spanish_result(self) -> None:
        answer = (
            "# Título\n\n## Resumen ejecutivo\nLa fuente explica el proceso y sus decisiones principales.\n\n"
            "## Mapa del contenido\n- Concepto\n\n## Desarrollo\n"
            "El sistema procesa la entrada y conserva los datos.\n\n"
            "## Procedimientos y métodos\n1. Preparar la entrada.\n\n## Referencia rápida\n- Dato: valor.\n\n"
            "## Tips y buenas prácticas\n- Verificar el resultado.\n\n## Errores comunes y cómo evitarlos\n"
            "- No comprobar los datos.\n\n## Ejemplos útiles\n- Ejemplo explicado.\n\n## Glosario\n"
            "- Entrada: información inicial.\n\n## Checklist final\n- [ ] Revisar.\n\n## Preguntas de repaso\n"
            "1. ¿Qué se procesa? La entrada.\n\n## Cobertura\nSe cubrieron los conceptos relevantes."
        )
        self.assertIsNone(study_notes_quality_error(answer, final=True))


if __name__ == "__main__":
    unittest.main()
