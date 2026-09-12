"""Run unittest after the same Tk initialization used by the desktop entry point.

Example: .venv/Scripts/python.exe -B tools/verify_desktop.py discover -s tests -v

Tras cada prueba se recoge la basura en el hilo principal. Las pruebas crean y
destruyen decenas de raíces Tk en un mismo proceso mientras siguen vivos hilos
de otras pruebas; una raíz destruida que queda en un ciclo de referencias la
libera el recolector en el hilo que esté activo, y si no es este, el intérprete
Tcl se borra fuera de su hilo y el proceso aborta con «Tcl_AsyncDelete: async
handler deleted by the wrong thread», sin resultado de unittest. Se reprodujo
con dos pruebas de la ventana seguidas de `test_reversion_ui`. La aplicación no
tiene ese escenario: una sola raíz en toda su vida.
"""
from __future__ import annotations

import gc
import sys
import unittest
from pathlib import Path


def _collect_after_each_test() -> None:
    original_run = unittest.TestCase.run

    def run(self, result=None):  # type: ignore[no-untyped-def]
        try:
            return original_run(self, result)
        finally:
            gc.collect()

    unittest.TestCase.run = run  # type: ignore[method-assign]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'src'), str(root)]
    from knowledge_orchestrator.ui.desktop_bootstrap import load_dashboard

    load_dashboard()
    _collect_after_each_test()
    unittest.main(module=None)


if __name__ == '__main__':
    main()
