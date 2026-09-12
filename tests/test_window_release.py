"""Cerrar la ventana la libera en el hilo que la cierra.

Si la ventana destruida queda en un ciclo de referencias, el recolector la
libera más tarde en cualquier hilo; al borrarse ahí el intérprete Tcl, el
proceso aborta con «Tcl_AsyncDelete: async handler deleted by the wrong thread».
Se reprodujo con dos pruebas de la ventana seguidas de otra con hilos de lectura.
"""
from __future__ import annotations

import tkinter as tk
import unittest
import weakref

from knowledge_orchestrator.ui.dashboard.base import DashboardBase


class _Window(DashboardBase):
    def __init__(self) -> None:
        tk.Tk.__init__(self)
        self.panel = tk.Frame(self)
        self.label = tk.Label(self.panel)
        self.value = tk.StringVar(self, value="x")


class WindowReleaseTests(unittest.TestCase):
    def test_destroy_releases_widgets_and_variables_without_waiting_for_the_collector(self) -> None:
        try:
            window = _Window()
        except tk.TclError as error:
            self.skipTest(f"Tcl/Tk no disponible: {error}")
        window.withdraw()
        label, value = weakref.ref(window.label), weakref.ref(window.value)

        window.destroy()

        self.assertIsNone(label(), "la ventana cerrada retiene sus widgets")
        self.assertIsNone(value(), "la ventana cerrada retiene sus variables Tk")
        self.assertEqual(window.tk.call("after", "info"), "")
        window.destroy()  # la segunda llamada no debe fallar


if __name__ == "__main__":
    unittest.main()
