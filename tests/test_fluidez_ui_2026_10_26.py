"""Regresiones del 26-oct-2026: la ventana se quedaba bloqueada al usarla.

La lista de Trabajo tardaba 6–12 s con la base real (765 documentos, ~2000
tareas de ~75 KB) porque buscaba la última tarea de cada documento recorriendo
la tabla entera, y el refresco la repetía cada 2 s en el hilo de Tk.
Arreglo A: índice (migración 029). Arreglo C: el refresco periódico lee en
segundo plano, así que ni una consulta lenta futura congela la ventana.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import unittest
from contextlib import closing

from knowledge_orchestrator.ui import lecturas_fondo
from knowledge_orchestrator.ui.lecturas_fondo import BackgroundSnapshots
from knowledge_orchestrator.ui.snapshots import WORK_ITEMS_SQL
from tests.helpers import generic_markdown
from tests.test_uso_real_2026_10_08 import RuntimeCase, _tk_available


class WorkItemsIndexTests(RuntimeCase):
    def test_latest_task_lookup_uses_the_index_instead_of_scanning_tasks(self) -> None:
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            plan = " | ".join(row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + WORK_ITEMS_SQL))
        self.assertIn("idx_tasks_capture_latest", plan)
        self.assertNotIn("SCAN latest", plan)


class SlowService:
    """Servicio de lectura cuyo resultado y bloqueo controla la prueba."""

    def __init__(self) -> None:
        self.value = "v1"
        self.gate = threading.Event()
        self.gate.set()
        self.calls = 0
        self.fail: BaseException | None = None

    def work_items(self) -> str:
        self.calls += 1
        self.gate.wait(10)
        if self.fail is not None:
            raise self.fail
        return self.value

    def library_page(self, *, search: str = "") -> str:
        return search


def wait_for(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("no ocurrió a tiempo")
        time.sleep(0.01)


class BackgroundSnapshotsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = SlowService()
        self.reads = BackgroundSnapshots(self.service)
        self.addCleanup(self.reads.close)
        self.addCleanup(self.service.gate.set)

    def idle(self) -> bool:
        with self.reads._lock:
            return not self.reads._pending

    def test_periodic_read_returns_at_once_while_the_query_is_slow(self) -> None:
        self.assertEqual(self.reads.work_items(), "v1")  # primera lectura: en el acto
        self.service.gate.clear()  # a partir de aquí la consulta «tarda»
        self.service.value = "v2"
        started = time.monotonic()
        with self.reads.periodic():
            self.assertEqual(self.reads.work_items(), "v1")
            self.assertEqual(self.reads.work_items(), "v1")
        self.assertLess(time.monotonic() - started, 0.5)
        self.service.gate.set()
        wait_for(self.idle)
        with self.reads.periodic():
            self.assertEqual(self.reads.work_items(), "v2")

    def test_only_one_background_read_per_query_at_a_time(self) -> None:
        self.reads.work_items()
        self.service.gate.clear()
        with self.reads.periodic():
            for _ in range(20):
                self.reads.work_items()
        self.service.gate.set()
        wait_for(self.idle)
        self.assertEqual(self.service.calls, 2)

    def test_reads_outside_the_periodic_refresh_are_always_fresh(self) -> None:
        self.assertEqual(self.reads.work_items(), "v1")
        self.service.value = "v2"
        self.assertEqual(self.reads.work_items(), "v2")

    def test_a_background_failure_is_reported_once_and_keeps_the_last_good_value(self) -> None:
        self.reads.work_items()
        self.service.fail = sqlite3.OperationalError("disk I/O error")
        with self.assertLogs("knowledge_orchestrator.ui.lecturas_fondo", level="ERROR"):
            with self.reads.periodic():
                self.reads.work_items()
            wait_for(self.idle)
        self.service.fail = None
        with self.reads.periodic():
            with self.assertRaises(sqlite3.OperationalError):
                self.reads.work_items()
            self.assertEqual(self.reads.work_items(), "v1")

    def test_an_older_background_read_never_overwrites_a_newer_one(self) -> None:
        self.reads.work_items()
        self.service.gate.clear()
        with self.reads.periodic():
            self.reads.work_items()  # lectura en segundo plano empezada con «v1»
        wait_for(lambda: self.service.calls == 2)
        self.service.value = "v3"
        self.reads._store(("work_items", (), ()), time.monotonic(), "v3")  # la de una acción, más reciente
        self.service.value = "v1"
        self.service.gate.set()
        wait_for(self.idle)
        with self.reads.periodic():
            self.assertEqual(self.reads.work_items(), "v3")

    def test_distinct_reads_are_bounded(self) -> None:
        for number in range(lecturas_fondo.MAX_CACHED_READS + 10):
            self.reads.library_page(search=str(number))
        self.assertEqual(len(self.reads._cache), lecturas_fondo.MAX_CACHED_READS)

    def test_close_stops_the_thread(self) -> None:
        self.reads.close()
        self.reads._thread.join(2)
        self.assertFalse(self.reads._thread.is_alive())


class WindowStaysResponsiveTests(RuntimeCase):
    """Con la ventana real: el refresco periódico no espera a una consulta lenta."""

    def setUp(self) -> None:
        super().setUp()
        _tk_available(self)
        from knowledge_orchestrator.ui.dashboard import OrchestratorDashboard

        self.window = OrchestratorDashboard(self.runtime)
        self.window.withdraw()
        self.addCleanup(self.window.destroy)
        self.errors: list[BaseException] = []
        self.window.report_callback_exception = lambda _type, value, _tb: self.errors.append(value)

    def test_periodic_refresh_does_not_wait_for_a_slow_work_list(self) -> None:
        window = self.window
        window._refresh(force=True)
        service = window.snapshots._service
        real = service.work_items
        gate = threading.Event()
        self.addCleanup(gate.set)

        def slow():
            gate.wait(3)
            return real()

        service.work_items = slow
        started = time.monotonic()
        for _ in range(3):
            window._refresh_tick()
            # update() correría el siguiente tick programado y, sin el arreglo, no acabaría nunca.
            window.update_idletasks()
        self.assertLess(time.monotonic() - started, 2.0, "la ventana esperó a la consulta lenta")
        self.assertEqual(self.errors, [])
        self.assertNotIn("se reintenta", window.status_var.get())

    def test_new_documents_appear_after_a_periodic_refresh(self) -> None:
        window = self.window
        window._refresh(force=True)
        before = len(window.snapshots.work_items())
        self.paths.ensure_directories()
        source = self.paths.inbox / "nuevo.md"
        source.write_bytes(generic_markdown(capture_id="nuevo", title="Nuevo", transcript="dato técnico " * 50))
        self.assertTrue(self.runtime.ingestion.ingest(source).accepted)
        deadline = time.monotonic() + 5
        while len(window._work_items) <= before and time.monotonic() < deadline:
            window._refresh_tick()
            window.update()
            time.sleep(0.05)
        self.assertGreater(len(window._work_items), before, "el documento nuevo no llegó a la lista")
        self.assertEqual(self.errors, [])

    def test_closing_the_window_stops_the_reader_thread(self) -> None:
        reads = self.window.snapshots
        self.window.destroy()
        reads._thread.join(2)
        self.assertFalse(reads._thread.is_alive())

