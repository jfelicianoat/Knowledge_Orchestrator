"""Vista «Trabajo»: el registro maestro-detalle de lo que está pasando.

FIRST VIEWPORT: lista filtrable a la izquierda, diagnóstico y cronología del
trabajo seleccionado a la derecha. Es la pantalla principal del panel.
El detalle vive en `trabajo_detalle` y las acciones en `trabajo_acciones`:
aquí queda la construcción, el filtrado y la selección.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Sequence
from functools import partial
from tkinter import ttk

from knowledge_orchestrator.ui.dashboard.trabajo_acciones import AccionesMixin


def resolve_work_selection(
    current: str | None,
    visible_ids: list[str],
    *,
    select_first: bool,
) -> str | None:
    """Mantiene el objetivo estable; solo elige uno nuevo por intención explícita."""

    if current in visible_ids:
        return current
    if current is None and select_first and visible_ids:
        return visible_ids[0]
    return None


def resolve_work_selections(
    current: Sequence[str],
    visible_ids: list[str],
    *,
    select_first: bool,
) -> tuple[str, ...]:
    """Conserva una selección múltiple durante los refrescos y filtros."""

    selected = set(current)
    retained = tuple(item_id for item_id in visible_ids if item_id in selected)
    if retained:
        return retained
    if select_first and visible_ids:
        return (visible_ids[0],)
    return ()


class TrabajoMixin(AccionesMixin):
    """Construcción de la pantalla, filtros y selección de la lista."""

    def _build_work(self) -> None:
        page = self._new_page("work")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        pane = tk.PanedWindow(page, orient="horizontal", bg=self.colors["border"], sashwidth=2,
                             bd=0, relief="flat", showhandle=False)
        pane.grid(row=0, column=0, sticky="nsew")

        left = tk.Frame(pane, bg=self.colors["surface"])
        right = tk.Frame(pane, bg=self.colors["surface"])
        pane.add(left, minsize=560, stretch="always")
        pane.add(right, minsize=430, stretch="always")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(5, weight=1)

        filter_row = tk.Frame(left, bg=self.colors["surface"])
        filter_row.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        self.filter_buttons: dict[str, tk.Button] = {}
        for key, label in (("active", "En proceso"), ("attention", "Necesitan atención"),
                           ("completed", "Finalizados"), ("all", "Todos")):
            button = tk.Button(
                filter_row, text=label, command=partial(self._set_work_filter, key),
                bg=self.colors["surface"], fg=self.colors["muted"], activebackground=self.colors["raised"],
                activeforeground=self.colors["text"], relief="flat", borderwidth=1,
                highlightthickness=1, highlightbackground=self.colors["border"], padx=13, pady=8,
                font=("Segoe UI Semibold", 9), cursor="hand2",
            )
            button.pack(side="left", padx=(0, 1))
            self.filter_buttons[key] = button

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_args: self._refresh_work_list())
        search_host = tk.Frame(left, bg=self.colors["surface"])
        search_host.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        search_host.columnconfigure(1, weight=1)
        tk.Label(
            search_host, text="Buscar documentos", bg=self.colors["surface"], fg=self.colors["muted"],
            font=("Segoe UI", 9), padx=0,
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))
        search = ttk.Entry(search_host, textvariable=self.search_var, style="Dark.TEntry")
        search.grid(row=0, column=1, sticky="ew")
        self.search_entry = search
        self.search_entry.insert(0, "")

        self.work_tree = ttk.Treeview(
            left,
            columns=("estado", "edad", "actualizado"),
            show="tree headings",
            style="Dark.Treeview",
            selectmode="extended",
        )
        self.work_tree.heading("#0", text="Documento")
        self.work_tree.heading("estado", text="Estado")
        self.work_tree.heading("edad", text="Edad")
        self.work_tree.heading("actualizado", text="Actualizado")
        self.work_tree.column("#0", width=390, minwidth=240)
        self.work_tree.column("estado", width=170, minwidth=130)
        self.work_tree.column("edad", width=75, minwidth=60, anchor="w")
        self.work_tree.column("actualizado", width=95, minwidth=80, anchor="w")
        self.work_tree.grid(row=2, column=0, sticky="nsew")
        self.work_tree.bind("<<TreeviewSelect>>", lambda _event: self._select_work())
        self.work_tree.tag_configure("attention", foreground="#ff9aa0")
        self.work_tree.tag_configure("completed", foreground="#a9e9bd")
        self.work_tree.tag_configure("active", foreground=self.colors["text"])
        scrollbar = ttk.Scrollbar(left, orient="vertical", command=self.work_tree.yview)
        scrollbar.grid(row=2, column=1, sticky="ns")
        self.work_tree.configure(yscrollcommand=scrollbar.set)
        self.work_summary_var = tk.StringVar(value="Sin documentos")
        tk.Label(left, textvariable=self.work_summary_var, bg=self.colors["surface"], fg=self.colors["muted"],
                 font=("Segoe UI", 9), anchor="w", padx=18, pady=12).grid(row=3, column=0, sticky="ew")

        detail_header = tk.Frame(right, bg=self.colors["surface"])
        detail_header.grid(row=0, column=0, sticky="ew", padx=26, pady=(24, 4))
        detail_header.columnconfigure(0, weight=1)
        self.detail_title_var = tk.StringVar(value="Selecciona un documento")
        self.detail_badge_var = tk.StringVar(value="")
        tk.Label(detail_header, textvariable=self.detail_title_var, bg=self.colors["surface"], fg=self.colors["text"],
                 font=("Segoe UI Semibold", 16), anchor="w", wraplength=540, justify="left").grid(
            row=0, column=0, sticky="ew"
        )
        self.detail_badge = tk.Label(
            detail_header, textvariable=self.detail_badge_var, bg=self.colors["raised"], fg=self.colors["muted"],
            font=("Segoe UI Semibold", 9), padx=10, pady=5,
        )
        self.detail_badge.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.detail_path_var = tk.StringVar(value="El detalle aparecerá aquí.")
        self.detail_id_var = tk.StringVar(value="")
        tk.Label(right, textvariable=self.detail_path_var, bg=self.colors["surface"], fg=self.colors["muted"],
                 font=("Segoe UI", 9), anchor="w", wraplength=680, justify="left").grid(
            row=1, column=0, sticky="ew", padx=26, pady=(0, 4)
        )
        tk.Label(right, textvariable=self.detail_id_var, bg=self.colors["surface"], fg=self.colors["muted"],
                 font=("Consolas", 8), anchor="w").grid(row=2, column=0, sticky="ew", padx=26, pady=(0, 14))

        self.issue_frame = tk.Frame(
            right, bg=self.colors["raised"], highlightbackground=self.colors["border"], highlightthickness=1
        )
        self.issue_frame.grid(row=3, column=0, sticky="ew", padx=26, pady=(0, 18))
        self.issue_title_var = tk.StringVar(value="No hay ningún documento seleccionado.")
        self.issue_message_var = tk.StringVar(value="Elige un documento de la lista para consultar su estado.")
        tk.Label(self.issue_frame, textvariable=self.issue_title_var, bg=self.colors["raised"], fg=self.colors["text"],
                 font=("Segoe UI Semibold", 11), anchor="w").pack(fill="x", padx=16, pady=(14, 5))
        tk.Label(
            self.issue_frame,
            textvariable=self.issue_message_var,
            bg=self.colors["raised"],
            fg=self.colors["muted"],
                 font=("Segoe UI", 9), anchor="w", justify="left", wraplength=640).pack(
            fill="x", padx=16, pady=(0, 14)
        )

        tk.Label(right, text="Línea de tiempo", bg=self.colors["surface"], fg=self.colors["text"],
                 font=("Segoe UI Semibold", 11), anchor="w").grid(row=4, column=0, sticky="ew", padx=26)
        self.timeline = tk.Text(
            right, height=10, wrap="word", bg=self.colors["surface"], fg=self.colors["muted"],
            insertbackground=self.colors["text"], relief="flat", borderwidth=0, padx=0, pady=8,
            font=("Segoe UI", 9), state="disabled", cursor="arrow",
        )
        self.timeline.grid(row=5, column=0, sticky="nsew", padx=26)
        self.timeline.tag_configure("time", foreground=self.colors["muted"], font=("Consolas", 8))
        self.timeline.tag_configure("event", foreground=self.colors["text"], font=("Segoe UI Semibold", 9))

        actions = tk.Frame(right, bg=self.colors["surface"])
        actions.grid(row=6, column=0, sticky="sew", padx=26, pady=(12, 14))
        tk.Label(actions, text="Acciones", bg=self.colors["surface"], fg=self.colors["text"],
                 font=("Segoe UI Semibold", 11), anchor="w").pack(fill="x", pady=(0, 9))
        action_buttons = tk.Frame(actions, bg=self.colors["surface"])
        action_buttons.pack(fill="x")
        action_buttons.columnconfigure((0, 1), weight=1)
        self.retry_button = ttk.Button(
            action_buttons, text="Enviar de nuevo", style="Accent.TButton", command=self._retry_selected
        )
        self.retry_button.grid(row=0, column=0, sticky="ew", padx=(0, 5), pady=(0, 8))
        self.open_location_button = ttk.Button(
            action_buttons, text="Abrir ubicación", style="Secondary.TButton", command=self._open_selected_location
        )
        self.open_location_button.grid(row=0, column=1, sticky="ew", padx=(5, 0), pady=(0, 8))
        self.ignore_button = ttk.Button(
            action_buttons, text="Ignorar este archivo", style="Danger.TButton", command=self._cancel_or_ignore_selected
        )
        self.ignore_button.grid(row=1, column=0, columnspan=2, sticky="ew")
        for accion in (self.retry_button, self.open_location_button, self.ignore_button):
            accion.state(["disabled"])

        self.technical_var = tk.StringVar(value="Detalles técnicos: —")
        self._technical_visible = False
        self.technical_button = tk.Button(
            right, text="Mostrar detalles técnicos", command=self._toggle_technical,
            bg=self.colors["surface"], fg=self.colors["muted"], activebackground=self.colors["raised"],
            activeforeground=self.colors["text"], relief="flat", borderwidth=0,
            font=("Segoe UI", 9), anchor="w", cursor="hand2",
        )
        self.technical_button.grid(row=7, column=0, sticky="ew", padx=22, pady=(0, 8))
        self.technical_label = tk.Label(
            right, textvariable=self.technical_var, bg=self.colors["surface"], fg=self.colors["muted"],
            font=("Consolas", 8), anchor="w", wraplength=680, justify="left",
        )
        self.technical_label.grid(row=8, column=0, sticky="ew", padx=26, pady=(0, 16))
        self.technical_label.grid_remove()

    def _refresh_work(self) -> None:
        items = self.snapshots.work_items()
        self._work_items = {item.capture_id: item for item in items}
        self._refresh_work_list(select_first=not self._work_selection_initialized)
        self._work_selection_initialized = True
        attention = [item for item in items if item.category == "attention"]
        self.dashboard_vars["failed"].set(str(len(attention)))
        self._replace_tree(
            self.home_attention,
            [(item.capture_id, (item.status_label, item.updated_label)) for item in attention[:8]],
            texts={item.capture_id: self._work_row_text(item) for item in attention[:8]},
            tags={item.capture_id: ("attention",) for item in attention[:8]},
        )
        self._sync_dashboard_cards()

    def _refresh_work_list(self, *, select_first: bool = False) -> None:
        if not hasattr(self, "work_tree"):
            return
        items = list(self._work_items.values())
        counts = {
            "active": sum(item.category == "active" for item in items),
            "attention": sum(item.category == "attention" for item in items),
            "completed": sum(item.category == "completed" for item in items),
            "all": len(items),
        }
        labels = {
            "active": "En proceso",
            "attention": "Necesitan atención",
            "completed": "Finalizados",
            "all": "Todos",
        }
        for key, button in self.filter_buttons.items():
            selected = key == self._work_filter
            button.configure(
                text=f"{labels[key]} ({counts[key]})",
                bg=self.colors["accent_dark"] if selected else self.colors["surface"],
                fg=self.colors["accent"] if selected else self.colors["muted"],
                highlightbackground=self.colors["accent"] if selected else self.colors["border"],
            )
        query = self.search_var.get().strip().casefold()
        visible = [
            item for item in items
            if (self._work_filter == "all" or item.category == self._work_filter)
            and (not query or query in " ".join((item.title, item.filename, item.path, item.status_label)).casefold())
        ]
        rows = [
            (item.capture_id, (item.status_label, self._format_elapsed(item.elapsed_seconds), item.updated_label))
            for item in visible
        ]
        self._replace_tree(
            self.work_tree, rows,
            texts={item.capture_id: self._work_row_text(item) for item in visible},
            tags={item.capture_id: (item.category,) for item in visible},
        )
        self.work_summary_var.set(
            f"Mostrando {len(visible)} de {len(items)} documentos"
            if items else "Aún no hay documentos. Importa uno para empezar."
        )
        visible_ids = [item.capture_id for item in visible]
        resolved = resolve_work_selections(
            self._selected_work_ids,
            visible_ids,
            select_first=select_first,
        )
        self._selected_work_ids = resolved
        if resolved:
            if self._selected_work_id not in resolved:
                self._selected_work_id = resolved[0]
            self.work_tree.selection_set(resolved)
            self.work_tree.see(self._selected_work_id)
            self._render_work_selection([self._work_items[item_id] for item_id in resolved])
        else:
            self._selected_work_id = None
            self._render_empty_detail()

    def _set_work_filter(self, value: str) -> None:
        self._work_filter = value
        self._selected_work_id = None
        self._selected_work_ids = ()
        self._refresh_work_list(select_first=True)

    def _select_work(self) -> None:
        selection = self.work_tree.selection()
        if not selection:
            self._selected_work_id = None
            self._selected_work_ids = ()
            self._render_empty_detail()
            return
        self._selected_work_ids = tuple(str(item_id) for item_id in selection if str(item_id) in self._work_items)
        focused = str(self.work_tree.focus())
        self._selected_work_id = focused if focused in self._selected_work_ids else self._selected_work_ids[0]
        self._render_work_selection([self._work_items[item_id] for item_id in self._selected_work_ids])

    def _focus_search(self) -> None:
        if self._current_page == "library":
            self.library_search_entry.focus_set()
            self.library_search_entry.selection_range(0, "end")
            return
        self._show_page("work")
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, "end")

    def _toggle_refresh(self) -> None:
        self._auto_refresh = not self._auto_refresh
        self.refresh_button.configure(text="Pausar actualización" if self._auto_refresh else "Reanudar actualización")
        self.status_var.set(
            "Actualización automática activa."
            if self._auto_refresh
            else "Actualización automática en pausa."
        )
        if self._auto_refresh:
            self._refresh(force=True)

    def _toggle_technical(self) -> None:
        self._technical_visible = not self._technical_visible
        self.technical_button.configure(
            text="Ocultar detalles técnicos" if self._technical_visible else "Mostrar detalles técnicos"
        )
        if self._technical_visible:
            self.technical_label.grid()
        else:
            self.technical_label.grid_remove()
