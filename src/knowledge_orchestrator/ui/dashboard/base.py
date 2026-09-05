"""Estado del panel y piezas que comparten todas las vistas.

Aquí está lo que no pertenece a ninguna pantalla: el estado de selección, la
creación de páginas, el cambio de página, el volcado de árboles y el cierre
limpio.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Sequence
from tkinter import ttk
from typing import Any

from knowledge_orchestrator.runtime import OrchestratorRuntime
from knowledge_orchestrator.services.broker_connection import BrokerConnectionStore
from knowledge_orchestrator.ui.dashboard.estilo import EstiloMixin
from knowledge_orchestrator.ui.snapshots import LibraryItem, ProfileItem, ReviewItem, UiSnapshotService, WorkItem
from knowledge_orchestrator.ui.startup import RuntimeStartup


class DashboardBase(EstiloMixin):
    """Ventana con estado, páginas y utilidades, todavía sin vistas."""

    refresh_ms = 2000

    # -- Puestos por los `_build_*` de cada vista. Son el contrato entre la
    # -- construcción y el resto del panel: si una vista deja de crear su
    # -- widget, el fallo sale aquí y no cuando alguien pulsa un botón.
    page_host: tk.Frame
    pages: dict[str, tk.Widget]
    _scrollable_canvases: dict[str, tk.Canvas]
    nav_buttons: dict[str, tk.Button]
    status_var: tk.StringVar
    refresh_button: tk.Button
    service_var: tk.StringVar
    broker_var: tk.StringVar
    clock_var: tk.StringVar
    dashboard_vars: dict[str, tk.StringVar]
    dashboard_card_vars: dict[str, tk.StringVar]
    system_message_var: tk.StringVar
    home_attention: ttk.Treeview
    search_var: tk.StringVar
    search_entry: ttk.Entry
    work_tree: ttk.Treeview
    work_summary_var: tk.StringVar
    detail_title_var: tk.StringVar
    detail_badge: tk.Label
    detail_badge_var: tk.StringVar
    detail_path_var: tk.StringVar
    detail_id_var: tk.StringVar
    issue_frame: tk.Frame
    issue_title_var: tk.StringVar
    issue_message_var: tk.StringVar
    timeline: tk.Text
    technical_var: tk.StringVar
    technical_button: tk.Button
    technical_label: tk.Label
    retry_button: ttk.Button
    open_location_button: ttk.Button
    ignore_button: ttk.Button
    review_tree: ttk.Treeview
    review_detail: tk.Text
    review_approve_button: ttk.Button
    review_reject_button: ttk.Button
    library_tree: ttk.Treeview
    library_search_var: tk.StringVar
    library_search_entry: ttk.Entry
    library_summary_var: tk.StringVar
    library_title_var: tk.StringVar
    library_meta_var: tk.StringVar
    library_path_var: tk.StringVar
    library_open_button: ttk.Button
    topics_tree: ttk.Treeview
    paths_var: tk.StringVar
    inbox_path_var: tk.StringVar
    results_path_var: tk.StringVar
    path_status_var: tk.StringVar
    broker_url_var: tk.StringVar
    broker_token_var: tk.StringVar
    broker_credential_var: tk.StringVar
    profiles_tree: ttk.Treeview
    capabilities_var: tk.StringVar
    save_profile_button: ttk.Button
    edit_prompt_button: ttk.Button

    # -- Costuras entre vistas. Las implementa quien las tiene: el refresco
    # -- completo lo conoce la ventana entera, y la lista de trabajos, su
    # -- vista. Declararlas aquí es lo que permite comprobarlas de verdad.

    def _refresh(self, *, force: bool = False) -> None:
        raise NotImplementedError  # pragma: no cover - lo implementa la ventana completa

    def _refresh_work_list(self, *, select_first: bool = False) -> None:
        raise NotImplementedError  # pragma: no cover - lo implementa la vista de trabajo

    def _refresh_library(self) -> None:
        raise NotImplementedError  # pragma: no cover - lo implementa la vista de biblioteca

    def __init__(self, runtime: OrchestratorRuntime) -> None:
        super().__init__()
        self.runtime = runtime
        self._startup = RuntimeStartup(runtime)
        self.snapshots = UiSnapshotService(runtime.database)
        self.connection_store = BrokerConnectionStore(runtime.paths)
        self.title("Knowledge Orchestrator")
        self.geometry("1440x900")
        self.minsize(1080, 680)
        self.configure(background=self.colors["root"])

        self._selected_review: ReviewItem | None = None
        self._review_items: dict[str, ReviewItem] = {}
        self._library_items: dict[str, LibraryItem] = {}
        self._selected_library_id: int | None = None
        self._library_search_job: str | None = None
        self._profile_items: dict[int, ProfileItem] = {}
        self._selected_profile_id: int | None = None
        self._work_items: dict[str, WorkItem] = {}
        self._selected_work_id: str | None = None
        self._selected_work_ids: tuple[str, ...] = ()
        self._work_filter = "active"
        self._work_selection_initialized = False
        self._auto_refresh = True
        self._current_page = "work"
        self._refresh_job: str | None = None
        self._scrollable_canvases = {}
        self.bind_all("<MouseWheel>", self._scroll_active_page, add="+")

    def _new_page(self, name: str) -> tk.Frame:
        page = tk.Frame(self.page_host, bg=self.colors["surface"])
        page.grid(row=0, column=0, sticky="nsew")
        self.pages[name] = page
        return page

    def _new_scrollable_page(self, name: str) -> tk.Frame:
        """Crea una página cuyo contenido sigue accesible en ventanas bajas."""

        outer = tk.Frame(self.page_host, bg=self.colors["surface"], highlightthickness=0)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)
        canvas = tk.Canvas(
            outer,
            bg=self.colors["surface"],
            highlightthickness=0,
            borderwidth=0,
        )
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        content = tk.Frame(canvas, bg=self.colors["surface"], highlightthickness=0)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")

        def fit_content_width(event: tk.Event) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        def update_scroll_region(_event: tk.Event) -> None:
            bounds = canvas.bbox("all")
            if bounds is not None:
                canvas.configure(scrollregion=bounds)

        canvas.bind("<Configure>", fit_content_width)
        content.bind("<Configure>", update_scroll_region)
        self.pages[name] = outer
        self._scrollable_canvases[name] = canvas
        return content

    def _scroll_active_page(self, event: tk.Event) -> None:
        canvas = self._scrollable_canvases.get(self._current_page)
        if canvas is None or not canvas.winfo_ismapped() or not event.delta:
            return
        canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _page_heading(self, page: tk.Frame, title: str, subtitle: str) -> None:
        heading = tk.Frame(page, bg=self.colors["surface"])
        heading.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 18))
        tk.Label(heading, text=title, bg=self.colors["surface"], fg=self.colors["text"],
                 font=("Segoe UI Semibold", 20), anchor="w").pack(fill="x")
        tk.Label(heading, text=subtitle, bg=self.colors["surface"], fg=self.colors["muted"],
                 font=("Segoe UI", 10), anchor="w").pack(fill="x", pady=(3, 0))

    def _show_page(self, page: str) -> None:
        self._current_page = page
        self.pages[page].tkraise()
        for key, button in self.nav_buttons.items():
            selected = key == page
            button.configure(
                fg=self.colors["text"] if selected else self.colors["muted"],
                bg=self.colors["raised"] if selected else self.colors["header"],
            )
        if page == "work":
            self.after_idle(self.search_entry.focus_set)
        elif page == "library":
            self._refresh_library()
            self.after_idle(self.library_search_entry.focus_set)

    def _drain_events(self) -> None:
        events = self.runtime.bridge.drain()
        if events:
            event = events[-1]
            self.status_var.set(event.message)

    def _selected_item(self) -> WorkItem | None:
        return self._work_items.get(self._selected_work_id or "")

    def _selected_items(self) -> tuple[WorkItem, ...]:
        """Devuelve toda la selección visible en el mismo orden que la lista."""

        return tuple(
            self._work_items[item_id]
            for item_id in self._selected_work_ids
            if item_id in self._work_items
        )

    @staticmethod
    def _replace_tree(
        tree: ttk.Treeview,
        rows: Sequence[tuple[str, tuple[object, ...]]],
        *,
        texts: dict[str, str] | None = None,
        tags: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        selected = set(tree.selection())
        current = set(tree.get_children())
        incoming = {row_id for row_id, _ in rows}
        for row_id in current - incoming:
            tree.delete(row_id)
        for row_id, values in rows:
            options: dict[str, Any] = {"values": values}
            if texts is not None:
                options["text"] = texts.get(row_id, "")
            if tags is not None:
                options["tags"] = tags.get(row_id, ())
            if row_id in current:
                tree.item(row_id, **options)
            else:
                tree.insert("", "end", iid=row_id, **options)
        keep = tuple(row_id for row_id in selected if row_id in incoming)
        if keep:
            tree.selection_set(keep)

    @staticmethod
    def _work_row_text(item: WorkItem) -> str:
        location = item.path or item.filename
        return f"{item.title}\n{location}"

    @staticmethod
    def _event_label(event_type: str) -> str:
        labels = {
            "CAPTURE_STAGED": "Documento preparado", "CAPTURE_PENDING": "Validación completada",
            "BROKER_TASK_ACCEPTED": "Broker aceptó la tarea", "CAPTURE_PROCESSING": "Procesamiento iniciado",
            "CAPTURE_COMPLETED": "Trabajo completado", "MANUAL_RETRY_REQUESTED": "Reintento solicitado",
            "CAPTURE_IGNORED": "Incidencia ignorada",
            "BROKER_RESULT_WARNING": "Aviso del Broker",
            "BROKER_CITATION_WARNING": "Revisión de citas necesaria",
        }
        return labels.get(event_type, event_type.replace("_", " ").capitalize())

    @staticmethod
    def _format_elapsed(seconds: int) -> str:
        minutes, rest = divmod(max(0, seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes:02d}m"
        if minutes:
            return f"{minutes}m"
        return f"{rest}s"

    def _close(self) -> None:
        if self._library_search_job is not None:
            self.after_cancel(self._library_search_job)
            self._library_search_job = None
        if self._refresh_job is not None:
            try:
                self.after_cancel(self._refresh_job)
            except tk.TclError:
                pass
            self._refresh_job = None
        try:
            self._startup.cancel()
        finally:
            self.destroy()
