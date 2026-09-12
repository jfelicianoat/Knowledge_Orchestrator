"""Vista «Documentos»: el registro maestro-detalle de lo que está pasando.

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

from knowledge_orchestrator.ui.dashboard.estilo import FONT, FONT_SEMIBOLD, MONO, TONES
from knowledge_orchestrator.ui.dashboard.trabajo_acciones import AccionesMixin

FILTERS = (("active", "En proceso"), ("attention", "Necesitan atención"),
           ("completed", "Finalizados"), ("all", "Todos"))


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
        c = self.colors
        page = self._new_page("work")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        pane = tk.PanedWindow(page, orient="horizontal", bg=c["border"], sashwidth=1,
                              bd=0, relief="flat", showhandle=False)
        pane.grid(row=0, column=0, sticky="nsew")

        left = tk.Frame(pane, bg=c["surface"])
        right = tk.Frame(pane, bg=c["surface"])
        pane.add(left, minsize=520, stretch="always")
        pane.add(right, minsize=440, stretch="always")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(3, weight=1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(6, weight=1)

        self._text(left, "Documentos", size=20, bold=True).grid(row=0, column=0, sticky="ew", padx=24,
                                                                  pady=(22, 12))
        filter_row = tk.Frame(left, bg=c["surface"])
        filter_row.grid(row=1, column=0, sticky="w", padx=24, pady=(0, 12))
        self.filter_buttons: dict[str, tk.Button] = {}
        for key, label in FILTERS:
            button = tk.Button(
                filter_row, text=label, command=partial(self._set_work_filter, key),
                bg=c["surface"], fg=c["muted"], activebackground=c["raised"], activeforeground=c["text"],
                relief="flat", borderwidth=0, highlightthickness=1, highlightbackground=c["border"],
                padx=12, pady=6, font=(FONT_SEMIBOLD, 9), cursor="hand2",
            )
            button.pack(side="left", padx=(0, 6))
            self.filter_buttons[key] = button

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_args: self._refresh_work_list())
        search_host = tk.Frame(left, bg=c["raised"], highlightbackground=c["border"], highlightthickness=1)
        search_host.grid(row=2, column=0, sticky="ew", padx=(24, 12), pady=(0, 12))
        self._icon(search_host, "search", size=11, color="faint", bg="raised").pack(side="left", padx=(12, 4))
        search = ttk.Entry(search_host, textvariable=self.search_var, style="Search.TEntry")
        search.pack(side="left", fill="x", expand=True)
        self._text(search_host, "Buscar por título o archivo · Ctrl+F", size=8, color="faint",
                   bg="raised").pack(side="right", padx=12)
        search.bind("<FocusIn>", lambda _event: search_host.configure(highlightbackground=c["accent"]))
        search.bind("<FocusOut>", lambda _event: search_host.configure(highlightbackground=c["border"]))
        self.search_entry = search

        self.work_tree = ttk.Treeview(
            left,
            columns=("estado", "actualizado"),
            show="tree headings",
            style="Dark.Treeview",
            selectmode="extended",
        )
        self.work_tree.heading("#0", text="Documento")
        self.work_tree.heading("estado", text="Estado")
        self.work_tree.heading("actualizado", text="Actualizado")
        self.work_tree.column("#0", width=330, minwidth=220, stretch=True)
        self.work_tree.column("estado", width=175, minwidth=140, stretch=False)
        self.work_tree.column("actualizado", width=110, minwidth=90, stretch=False)
        self.work_tree.grid(row=3, column=0, sticky="nsew", padx=(24, 0))
        self.work_tree.bind("<<TreeviewSelect>>", lambda _event: self._select_work())
        self.work_tree.tag_configure("error", foreground="#ff9aa0")
        self.work_tree.tag_configure("warning", foreground="#f5c56b")
        self.work_tree.tag_configure("success", foreground="#a9e9bd")
        self.work_tree.tag_configure("accent", foreground=c["text"])
        self.work_tree.tag_configure("neutral", foreground=c["text"])
        scrollbar = ttk.Scrollbar(left, orient="vertical", command=self.work_tree.yview)
        scrollbar.grid(row=3, column=1, sticky="ns", padx=(0, 12))
        self.work_tree.configure(yscrollcommand=scrollbar.set)
        self.work_summary_var = tk.StringVar(value="Sin documentos")
        self._text(left, textvariable=self.work_summary_var, size=9, color="faint").grid(
            row=4, column=0, sticky="ew", padx=24, pady=10)

        detail_header = tk.Frame(right, bg=c["surface"])
        detail_header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 4))
        detail_header.columnconfigure(0, weight=1)
        self.detail_title_var = tk.StringVar(value="Selecciona un documento")
        self.detail_badge_var = tk.StringVar(value="")
        tk.Label(detail_header, textvariable=self.detail_title_var, bg=c["surface"], fg=c["text"],
                 font=(FONT_SEMIBOLD, 17), anchor="w", wraplength=520, justify="left").grid(
            row=0, column=0, sticky="ew"
        )
        self.detail_badge = tk.Label(
            detail_header, textvariable=self.detail_badge_var, bg=c["surface"], fg=c["muted"],
            font=(FONT_SEMIBOLD, 9), padx=10, pady=4,
        )
        self.detail_badge.grid(row=0, column=1, sticky="ne", padx=(12, 0), pady=(4, 0))
        self.detail_path_var = tk.StringVar(value="El detalle aparecerá aquí.")
        self.detail_id_var = tk.StringVar(value="")
        self._text(right, textvariable=self.detail_path_var, size=9, color="muted", wraplength=620).grid(
            row=1, column=0, sticky="ew", padx=28, pady=(0, 2))
        tk.Label(right, textvariable=self.detail_id_var, bg=c["surface"], fg=c["faint"],
                 font=(MONO, 8), anchor="w").grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 6))

        self.work_steps = tk.Canvas(right, height=64, bg=c["surface"], highlightthickness=0)
        self.work_steps.grid(row=3, column=0, sticky="ew", padx=20, pady=(6, 4))
        self._work_steps_state: tuple[int, str] | None = None
        self.work_steps.bind("<Configure>", lambda _event: self._draw_work_steps())

        self.issue_frame = self._card(right)
        self.issue_frame.grid(row=4, column=0, sticky="ew", padx=28, pady=(6, 18))
        self.issue_frame.columnconfigure(2, weight=1)
        self.issue_bar = tk.Frame(self.issue_frame, bg=c["border"], width=4)
        self.issue_bar.grid(row=0, column=0, rowspan=3, sticky="ns")
        self.issue_icon = self._icon(self.issue_frame, "info", size=16, bg="raised")
        self.issue_icon.grid(row=0, column=1, sticky="nw", padx=(14, 10), pady=(14, 0))
        self.issue_title_var = tk.StringVar(value="No hay ningún documento seleccionado.")
        self.issue_message_var = tk.StringVar(value="Elige un documento de la lista para consultar su estado.")
        self.issue_title_label = self._text(self.issue_frame, textvariable=self.issue_title_var, size=11,
                                            bold=True, bg="raised")
        self.issue_title_label.grid(row=0, column=2, sticky="ew", padx=(0, 16), pady=(13, 3))
        self._text(self.issue_frame, textvariable=self.issue_message_var, size=9, color="muted", bg="raised",
                   wraplength=560).grid(row=1, column=2, sticky="ew", padx=(0, 16))
        # Dos filas: en ventanas estrechas las tres seguidas se salían por la derecha.
        action_buttons = tk.Frame(self.issue_frame, bg=c["raised"])
        action_buttons.grid(row=2, column=2, sticky="ew", padx=(0, 16), pady=(12, 14))
        primary = tk.Frame(action_buttons, bg=c["raised"])
        primary.pack(fill="x")
        self.retry_button = ttk.Button(
            primary, text="Enviar de nuevo", style="Accent.TButton", command=self._retry_selected
        )
        self.retry_button.pack(side="left", padx=(0, 8))
        self.open_location_button = ttk.Button(
            primary, text="Abrir ubicación", command=self._open_selected_location
        )
        self.open_location_button.pack(side="left")
        self.ignore_button = ttk.Button(
            action_buttons, text="Ignorar este archivo", style="Danger.TButton", command=self._cancel_or_ignore_selected
        )
        self.ignore_button.pack(anchor="w", pady=(6, 0))
        for accion in (self.retry_button, self.open_location_button, self.ignore_button):
            accion.state(["disabled"])

        self._text(right, "Línea de tiempo", size=11, bold=True).grid(row=5, column=0, sticky="ew", padx=28)
        self.timeline = tk.Text(
            right, height=10, wrap="word", bg=c["surface"], fg=c["muted"],
            insertbackground=c["text"], relief="flat", borderwidth=0, padx=0, pady=8,
            font=(FONT, 9), state="disabled", cursor="arrow", highlightthickness=0, spacing1=4,
        )
        self.timeline.grid(row=6, column=0, sticky="nsew", padx=28)
        self.timeline.tag_configure("time", foreground=c["faint"], font=(MONO, 8))
        self.timeline.tag_configure("event", foreground=c["text"], font=(FONT_SEMIBOLD, 9))
        self.timeline.tag_configure("message", foreground=c["muted"], lmargin1=34, lmargin2=34)
        for tone, (_background, foreground) in TONES.items():
            self.timeline.tag_configure(f"dot_{tone}", foreground=foreground)

        self.technical_var = tk.StringVar(value="Detalles técnicos: —")
        self._technical_visible = False
        self.technical_button = tk.Button(
            right, text="▸  Mostrar detalles técnicos", command=self._toggle_technical,
            bg=c["surface"], fg=c["muted"], activebackground=c["raised"],
            activeforeground=c["text"], relief="flat", borderwidth=0,
            font=(FONT, 9), anchor="w", cursor="hand2",
        )
        self.technical_button.grid(row=7, column=0, sticky="ew", padx=24, pady=(4, 8))
        self.technical_label = tk.Label(
            right, textvariable=self.technical_var, bg=c["surface"], fg=c["muted"],
            font=(MONO, 8), anchor="w", wraplength=640, justify="left",
        )
        self.technical_label.grid(row=8, column=0, sticky="ew", padx=28, pady=(0, 16))
        self.technical_label.grid_remove()

    def _refresh_work(self) -> None:
        items = self.snapshots.work_items()
        self._work_items = {item.capture_id: item for item in items}
        self._refresh_work_list(select_first=not self._work_selection_initialized)
        self._work_selection_initialized = True
        attention = [item for item in items if item.category == "attention"]
        self.dashboard_vars["failed"].set(str(len(attention)))
        shown = attention[:8]
        self._replace_tree(
            self.home_attention,
            [(item.capture_id, (self._status_text(item), self._relative_label(item.updated_at))) for item in shown],
            texts={item.capture_id: self._work_row_text(item) for item in shown},
            tags={item.capture_id: (self._work_tone(item),) for item in shown},
        )
        self._toggle_home_empty(not attention)
        self._sync_dashboard_cards()

    def _refresh_work_list(self, *, select_first: bool = False) -> None:
        if not hasattr(self, "work_tree"):
            return
        c = self.colors
        items = list(self._work_items.values())
        counts = {
            "active": sum(item.category == "active" for item in items),
            "attention": sum(item.category == "attention" for item in items),
            "completed": sum(item.category == "completed" for item in items),
            "all": len(items),
        }
        for key, label in FILTERS:
            button = self.filter_buttons[key]
            selected = key == self._work_filter
            button.configure(
                text=f"{label}  {counts[key]}",
                bg=c["accent_dark"] if selected else c["surface"],
                fg=c["accent"] if selected else c["muted"],
                highlightbackground=c["accent"] if selected else c["border"],
            )
        query = self.search_var.get().strip().casefold()
        visible = [
            item for item in items
            if (self._work_filter == "all" or item.category == self._work_filter)
            and (not query or query in " ".join((item.title, item.filename, item.path, item.status_label)).casefold())
        ]
        rows = [
            (item.capture_id, (self._status_text(item), self._relative_label(item.updated_at)))
            for item in visible
        ]
        self._replace_tree(
            self.work_tree, rows,
            texts={item.capture_id: self._work_row_text(item) for item in visible},
            tags={item.capture_id: (self._work_tone(item),) for item in visible},
        )
        if not items:
            summary = "Aún no hay documentos. Pulsa «Importar documentos» o déjalos en la carpeta vigilada."
        elif not visible and query:
            summary = f"Ningún documento coincide con «{self.search_var.get().strip()}»."
        else:
            summary = f"Mostrando {len(visible)} de {len(items)} documentos"
        self.work_summary_var.set(summary)
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
            text="▾  Ocultar detalles técnicos" if self._technical_visible else "▸  Mostrar detalles técnicos"
        )
        if self._technical_visible:
            self.technical_label.grid()
        else:
            self.technical_label.grid_remove()
