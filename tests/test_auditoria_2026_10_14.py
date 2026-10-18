"""Regresiones de la auditoría humana de UI del 14-oct-2026 (docs/Pruebas/Auditoria_KO_2026-10-14).

Cada prueba reproduce lo que vio quien auditaba: un botón inactivo que parecía
activo, un cancelado contado como «Finalizado», jerga interna en pantalla, un
duplicado que solo se veía en disco o un log sin rastro del pipeline.
"""
from __future__ import annotations

import logging
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from unittest import mock

from knowledge_orchestrator.services.markdown_import import parse_typed_paths
from knowledge_orchestrator.ui.dashboard.conocimiento import fit_text
from knowledge_orchestrator.ui.dashboard.trabajo import work_filter_key
from knowledge_orchestrator.ui.dashboard.trabajo_detalle import DetalleMixin, humane_phase
from knowledge_orchestrator.ui.proposal_audit_presenter import actor_label
from knowledge_orchestrator.worker.event_log_worker import EventLogWorker
from tests.helpers import generic_markdown
from tests.test_uso_real_2026_10_08 import RuntimeCase, _tk_available


def _item(**changes):
    from tests.test_ui_redesign import item

    return item(**changes)


class CancelledDocumentTests(RuntimeCase):
    """I-01b / I-03: un cancelado se puede volver a procesar y no cuenta como «Finalizado»."""

    def cancelled(self, capture_id: str):
        self.paths.ensure_directories()
        source = self.paths.inbox / f"{capture_id}.md"
        source.write_bytes(generic_markdown(capture_id=capture_id, title="Doc", transcript="Texto aportado."))
        self.assertTrue(self.runtime.ingestion.ingest(source).accepted)
        self.runtime.workflow_planner.plan_capture(capture_id)
        self.assertTrue(self.runtime.workflow_repository.cancel_capture(capture_id))
        return next(i for i in self.snapshots.work_items() if i.capture_id == capture_id)

    def test_cancelled_document_has_its_own_tab_and_can_be_reprocessed(self) -> None:
        item = self.cancelled("cancelado")
        self.assertEqual((item.status, item.category), ("CANCELLED", "completed"))
        self.assertEqual(work_filter_key(item), "cancelled")
        self.assertTrue(DetalleMixin._can_send_item(item))

        self.assertTrue(self.runtime.workflow_repository.reopen_failed_capture("cancelado"))
        self.assertIn("cancelado", self.runtime.workflow_repository.list_unplanned_capture_ids())
        # Se planifica una revisión nueva: la clave idempotente no choca con la cancelada.
        self.runtime.workflow_planner.plan_capture("cancelado")
        item = next(i for i in self.snapshots.work_items() if i.capture_id == "cancelado")
        self.assertEqual(work_filter_key(item), "active")

    def test_published_document_stays_in_finished(self) -> None:
        self.assertEqual(work_filter_key(_item(status="COMPLETED", category="completed")), "completed")
        self.assertEqual(work_filter_key(_item(status="DRAFT_REJECTED", category="completed")), "cancelled")


class PlainLanguageTests(unittest.TestCase):
    """I-08 / I-09: ni fases del Broker en inglés ni marcadores internos."""

    def test_broker_phases_are_spanish_and_unknown_ones_do_not_leak(self) -> None:
        self.assertEqual(humane_phase(_item(phase="generating")), "El modelo está generando la respuesta")
        self.assertEqual(humane_phase(_item(phase="some_new_phase")), "El Broker lo está procesando")

    def test_actors_read_as_words(self) -> None:
        self.assertEqual(actor_label("broker:comparison"), "análisis automático del Broker")
        self.assertEqual(actor_label("ui"), "tú, desde la aplicación")
        self.assertEqual(actor_label("api:agora-lector"), "consumidor de la API «agora-lector»")
        self.assertEqual(actor_label(None), "sin dato")


class TypedPathsTests(unittest.TestCase):
    """I-05: rutas pegadas con «/», con comillas o una por línea."""

    def test_forward_slashes_quotes_and_lines(self) -> None:
        self.assertEqual(parse_typed_paths("D:/tmp/nota.md"), [Path("D:/tmp/nota.md")])
        self.assertEqual(parse_typed_paths('"D:/a b/x.md" "C:\\c d\\y.txt"'),
                         [Path("D:/a b/x.md"), Path("C:/c d/y.txt")])
        self.assertEqual(parse_typed_paths("D:/a b/x.md\n\nD:/a b/x.md\nC:\\y.md\n"),
                         [Path("D:/a b/x.md"), Path("C:/y.md")])
        self.assertEqual(parse_typed_paths("   "), [])


class NativeDialogPathTests(unittest.TestCase):
    """I-05 dentro del propio diálogo de Windows (verificado además con el diálogo real y pywinauto)."""

    def test_typed_slashes_become_backslashes_except_urls(self) -> None:
        from knowledge_orchestrator.ui.dialogos import _fix_slashes

        self.assertEqual(_fix_slashes("D:/Proyectos TFM/nota.md"), r"D:\Proyectos TFM\nota.md")
        self.assertIsNone(_fix_slashes(r"D:\ya\bien.md"))
        self.assertIsNone(_fix_slashes("https://ejemplo.es/a.md"))

    def test_quoted_absolute_path_is_not_glued_to_the_open_folder(self) -> None:
        from knowledge_orchestrator.ui.dialogos import chosen_path

        self.assertEqual(chosen_path("D:/tmp/D:/tmp/nota.md"), "D:/tmp/nota.md")
        self.assertEqual(chosen_path("C:/datos/nota.md"), "C:/datos/nota.md")


class EventLogTests(RuntimeCase):
    """OBS-LOG: lo que pasa en el pipeline llega a orchestrator.log."""

    def test_new_events_are_logged_once_without_details(self) -> None:
        worker = EventLogWorker(self.runtime.database)
        self.runtime.repository.record_event("FILE_LOCKED", "En uso", details={"secreto": "no-sale"})
        with self.assertLogs("knowledge_orchestrator.events", level=logging.INFO) as logs:
            self.assertEqual(worker.flush(), 1)
        self.assertIn("FILE_LOCKED", logs.output[0])
        self.assertNotIn("no-sale", logs.output[0])
        self.assertEqual(worker.flush(), 0)


class HeldClaimsCountTests(RuntimeCase):
    """I-15: el resumen cuenta las afirmaciones retenidas en vez de hacerlas desaparecer."""

    def test_counts_expose_held_claims(self) -> None:
        from knowledge_orchestrator.ui.operations_snapshots import OperationsSnapshots

        counts = OperationsSnapshots(self.runtime.database).counts()
        self.assertEqual((counts["current"], counts["held"]), (0, 0))


class WindowTests(RuntimeCase):
    def setUp(self) -> None:
        super().setUp()
        _tk_available(self)
        from knowledge_orchestrator.ui.dashboard import OrchestratorDashboard

        self.window = OrchestratorDashboard(self.runtime)
        self.window.withdraw()
        self.addCleanup(self.window.destroy)
        self.errors: list[BaseException] = []
        self.window.report_callback_exception = lambda _type, value, _tb: self.errors.append(value)

    def test_disabled_buttons_drop_the_focus_ring_and_dim(self) -> None:
        """I-01: deshabilitado gana al foco; antes el borde acento lo hacía parecer pulsable."""

        style = ttk.Style(self.window)
        colors = self.window.colors
        for name in ("TButton", "Accent.TButton", "Secondary.TButton", "Danger.TButton"):
            border = style.map(name, "bordercolor")
            self.assertEqual(tuple(border[0][:-1]), ("disabled",), name)
            self.assertEqual(style.lookup(name, "foreground", ("disabled",)), colors["faint"], name)
            self.assertEqual(style.lookup(name, "background", ("disabled", "focus")), colors["surface"], name)

    def test_empty_selection_shows_no_issue_actions(self) -> None:
        """I-02: sin documento seleccionado no hay bloque de incidencia ni acciones."""

        window = self.window
        window._render_empty_detail()
        window.update_idletasks()
        self.assertFalse(window.issue_frame.winfo_manager())
        window._render_work_selection([_item(status="READY", task_id="t", category="active")])
        self.assertEqual(window.issue_frame.winfo_manager(), "grid")

    def test_cancelled_tab_is_counted_apart(self) -> None:
        window = self.window
        window._work_items = {
            "a": _item(capture_id="a", status="COMPLETED", category="completed"),
            "b": _item(capture_id="b", status="CANCELLED", category="completed"),
        }
        window._refresh_work_list()
        self.assertTrue(window.filter_buttons["completed"].cget("text").endswith("  1"))
        self.assertTrue(window.filter_buttons["cancelled"].cget("text").endswith("  1"))

    def test_new_source_starts_empty_and_requires_a_url(self) -> None:
        """I-07: se guardaba «Nueva fuente · https://example.org» sin querer."""

        window = self.window
        with mock.patch("knowledge_orchestrator.ui.dashboard.fuentes.messagebox.showerror") as error:
            window._edit_source()
            dialog = next(w for w in window.winfo_children() if isinstance(w, tk.Toplevel))
            entries = [w for w in dialog.winfo_children() if isinstance(w, ttk.Entry)]
            self.assertEqual(entries[0].get(), "")  # nombre
            self.assertEqual(entries[1].get(), "")  # URL
            entries[0].insert(0, "Blog")
            save = next(b for f in dialog.winfo_children() if isinstance(f, ttk.Frame)
                        for b in f.winfo_children() if isinstance(b, ttk.Button) and b.cget("text") == "Guardar fuente")
            save.invoke()
            self.assertIn("dirección", error.call_args.args[1])
            entries[1].insert(0, "no-es-url")
            save.invoke()
            self.assertIn("La URL no es válida", error.call_args.args[1])
            dialog.destroy()
        self.assertEqual(self.runtime.sources.repository.list_sources(), [])
        self.assertEqual(self.errors, [])

    def test_ellipsis_marks_truncated_claims(self) -> None:
        """I-12: el texto recortado termina en «…» y cabe en la columna."""

        font = tkfont.Font(root=self.window, family="Segoe UI", size=10)
        text = "Las afirmaciones largas se recortan sin pegarse a la columna siguiente " * 3
        fitted = fit_text(text, font, 200)
        self.assertTrue(fitted.endswith("…"))
        self.assertLessEqual(font.measure(fitted), 200)
        self.assertEqual(fit_text("corta", font, 200), "corta")

    def test_enter_activates_the_focused_button(self) -> None:
        """I-14: Enter pulsa el botón ttk con el foco, como en cualquier diálogo de Windows."""

        pressed = []
        host = tk.Toplevel(self.window)
        self.addCleanup(host.destroy)
        button = ttk.Button(host, text="Crear", command=lambda: pressed.append(1))
        button.pack()
        host.update()
        button.focus_force()
        button.event_generate("<Return>", when="tail")
        host.update()
        self.assertEqual(pressed, [1])

    def test_tab_reaches_filter_tabs_and_never_enters_hidden_pages(self) -> None:
        """I-16 (teclado): el foco no se pierde en páginas ocultas y las pestañas de filtro se alcanzan."""

        window = self.window
        window.deiconify()
        window._show_page("work")
        window.update()
        current = window.search_entry
        chain = []
        for _ in range(80):
            current = window.nametowidget(window.tk.call("tk_focusNext", current))
            chain.append(current)
            if current is window.search_entry:
                break
        self.assertIs(chain[-1], window.search_entry, "el ciclo de Tab no vuelve al buscador")
        hidden = [w for w in chain if not str(w).startswith(str(window.pages["work"]))
                  and any(str(w).startswith(str(page)) for page in window.pages.values())]
        self.assertEqual(hidden, [], "Tab entra en páginas que no se ven")
        self.assertTrue(set(window.filter_buttons.values()) <= set(chain))

    def test_typed_proposal_reason_dialog_is_spanish(self) -> None:
        """I-10: «Aceptar/Cancelar» en lugar de «OK/Cancel»."""

        from knowledge_orchestrator.ui.dialogos import ask_text

        seen = {}

        def answer() -> None:
            dialog = next((w for w in self.window.winfo_children()
                           if isinstance(w, tk.Toplevel) and w.title() == "Motivo"), None)
            if dialog is None:
                self.window.after(50, answer)
                return
            buttons = [b for f in dialog.winfo_children() for g in f.winfo_children()
                       for b in g.winfo_children() if isinstance(b, ttk.Button)]
            seen["texts"] = sorted(b.cget("text") for b in buttons)
            next(b for b in buttons if b.cget("text") == "Aceptar").invoke()

        self.window.after(50, answer)
        self.assertEqual(ask_text(self.window, "Motivo", "¿Por qué?", initial="porque sí"), "porque sí")
        self.assertEqual(seen["texts"], ["Aceptar", "Cancelar"])


class ReviewBlockReasonTests(unittest.TestCase):
    """I-01c: «Aplicar cambio» sin puente de Obsidian dice por qué, junto al botón."""

    from tests import test_phase_six_semantic_maintenance as _phase_six

    setUp = _phase_six.PhaseSixSemanticMaintenanceTests.setUp
    tearDown = _phase_six.PhaseSixSemanticMaintenanceTests.tearDown
    publish = _phase_six.PhaseSixSemanticMaintenanceTests.publish
    extraction = staticmethod(_phase_six.PhaseSixSemanticMaintenanceTests.extraction)
    prepare_candidate = _phase_six.PhaseSixSemanticMaintenanceTests.prepare_candidate

    def test_blocked_apply_explains_the_missing_bridge(self) -> None:
        _tk_available(self)
        from knowledge_orchestrator.ui.dashboard import OrchestratorDashboard

        _old, _new, pending_id, _before, after = self.prepare_candidate()
        candidate_id = self.runtime.semantic_maintenance.compare(pending_id, {
            'relation': 'SUPERSEDES', 'confidence': 0.99, 'impact': 'HIGH',
            'rationale': 'Nueva versión explícita.', 'replacement_text': after}).candidate_id
        window = OrchestratorDashboard(self.runtime)
        window.withdraw()
        self.addCleanup(window.destroy)
        maintenance = self.runtime.semantic_maintenance
        with mock.patch.object(maintenance, "editor_ready", return_value=False):
            window._refresh_reviews()
            window.review_tree.selection_set(str(candidate_id))
            window.review_tree.focus(str(candidate_id))
            window._select_review()
        self.assertIn("disabled", window.review_approve_button.state())
        self.assertIn("puente de Obsidian", window.review_block_var.get())
        with mock.patch.object(maintenance, "editor_ready", return_value=True):
            window._select_review()
        self.assertEqual(window.review_block_var.get(), "")


class AccessibilityTests(unittest.TestCase):
    """I-16: tipo, nombre y valor que se anuncian a los lectores de pantalla (verificado además con UIA real)."""

    def setUp(self) -> None:
        _tk_available(self)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

    def test_controls_describe_role_name_value_and_state(self) -> None:
        from knowledge_orchestrator.ui import accesibilidad as a11y

        form = ttk.Frame(self.root)
        ttk.Label(form, text="URL").grid(row=0, column=0)
        url = ttk.Entry(form)
        url.grid(row=0, column=1)
        url.insert(0, "https://ejemplo.es")
        secret = ttk.Entry(form, show="•")
        secret.accessible_name = "Token"  # type: ignore[attr-defined]
        secret.insert(0, "no-se-lee")
        button = ttk.Button(form, text="Guardar")
        button.state(["disabled"])
        self.assertEqual(a11y.describe(url)[:3], (a11y.ROLE_TEXT, "URL", "https://ejemplo.es"))
        self.assertEqual(a11y.describe(secret)[1:3], ("Token", ""))
        role, name, _value, state = a11y.describe(button)
        self.assertEqual((role, name), (a11y.ROLE_PUSHBUTTON, "Guardar"))
        self.assertTrue(state & a11y.STATE_UNAVAILABLE)
        self.assertIsNone(a11y.describe(ttk.Label(form, text="solo texto")))

    def test_field_takes_the_nearest_label_in_its_row_and_ignores_icon_glyphs(self) -> None:
        """Detectado con NVDA real: el buscador se anunciaba con el código del icono."""
        from knowledge_orchestrator.ui import accesibilidad as a11y

        row = ttk.Frame(self.root)
        ttk.Label(row, text="Vigencia").grid(row=0, column=0)
        ttk.Combobox(row).grid(row=0, column=1)
        ttk.Label(row, text="Entidad o texto").grid(row=0, column=2)
        query = ttk.Entry(row)
        query.grid(row=0, column=3)
        self.assertEqual(a11y.label_for(query), "Entidad o texto")
        host = tk.Frame(self.root)
        tk.Label(host, text=chr(0xE721)).pack(side="left")
        search = ttk.Entry(host)
        search.pack(side="left")
        self.assertNotIn(chr(0xE721), a11y.label_for(search))

    def test_tree_value_is_the_focused_row_and_nav_frames_skip_icon_glyphs(self) -> None:
        from knowledge_orchestrator.ui import accesibilidad as a11y

        tree = ttk.Treeview(self.root, columns=("estado",))
        tree.heading("#0", text="Documentos")
        tree.insert("", "end", iid="a", text="Informe", values=("Cancelado",))
        tree.focus("a")
        self.assertEqual(a11y.describe(tree)[1:3], ("Documentos", "Informe · Cancelado"))
        nav = tk.Frame(self.root, takefocus=1)
        tk.Label(nav, text="").pack()
        tk.Label(nav, text="Inicio").pack()
        self.assertEqual(a11y.describe(nav)[:2], (a11y.ROLE_PUSHBUTTON, "Inicio"))


if __name__ == "__main__":
    unittest.main()
