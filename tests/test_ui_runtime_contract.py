"""El panel solo puede usar atributos que el runtime tenga de verdad.

Se comprueba estáticamente porque el fallo que motiva esta prueba no aparecía
hasta que alguien pulsaba un botón: el panel llamaba a
`runtime.ingestion_worker` y el campo se llama `worker`. Importar documentos o
reintentar una ingesta reventaba con AttributeError, y las pruebas normales no
lo veían porque no abren la ventana.

Mypy lo detectaba, pero sus avisos sobre este módulo llevaban tiempo
ignorándose. Esta prueba lo deja atado aunque alguien vuelva a mirar para otro
lado.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from knowledge_orchestrator.runtime import OrchestratorRuntime

PANEL = Path(__file__).resolve().parent.parent / "src" / "knowledge_orchestrator" / "ui" / "dashboard.py"


def _atributos_de_runtime_usados(ruta: Path) -> set[str]:
    """Todo lo que el módulo pide a `self.runtime`."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    usados: set[str] = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Attribute):
            continue
        objetivo = nodo.value
        if (
            isinstance(objetivo, ast.Attribute)
            and objetivo.attr == "runtime"
            and isinstance(objetivo.value, ast.Name)
            and objetivo.value.id == "self"
        ):
            usados.add(nodo.attr)
    return usados


class UiRuntimeContractTest(unittest.TestCase):
    def test_el_panel_no_inventa_atributos_del_runtime(self) -> None:
        usados = _atributos_de_runtime_usados(PANEL)
        self.assertTrue(usados, "no se detectó ningún uso de self.runtime: ¿cambió la forma del panel?")

        disponibles = set(OrchestratorRuntime.__annotations__) | {
            nombre for nombre in dir(OrchestratorRuntime) if not nombre.startswith("_")
        }
        inventados = sorted(usados - disponibles)
        self.assertEqual(
            inventados,
            [],
            f"el panel usa atributos que OrchestratorRuntime no tiene: {inventados}. "
            f"Disponibles: {sorted(disponibles)}",
        )

    def test_el_worker_de_ingesta_se_llama_worker(self) -> None:
        """El nombre concreto del fallo, por si alguien lo reintroduce."""
        self.assertIn("worker", OrchestratorRuntime.__annotations__)
        self.assertNotIn("ingestion_worker", OrchestratorRuntime.__annotations__)
        self.assertNotIn("ingestion_worker", PANEL.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
