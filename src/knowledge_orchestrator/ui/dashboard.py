from __future__ import annotations

import os
import shutil
import tkinter as tk
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from knowledge_orchestrator.runtime import OrchestratorRuntime
from knowledge_orchestrator.ui.snapshots import ReviewItem, UiSnapshotService, WorkItem


class OrchestratorDashboard(tk.Tk):
    """Interfaz de operaciones de Knowledge Orchestrator.

    THESIS: el trabajo activo es el producto; se rechaza la cuadrícula de métricas
    como pantalla principal.
    OWN-WORLD: superficies grafito, divisores precisos, texto claro y cian reservado
    para acción, selección y actividad.
    STORY: el usuario ve qué documentos avanzan, detecta qué requiere atención y actúa.
    FIRST VIEWPORT: navegación y acciones arriba; lista filtrable a la izquierda;
    diagnóstico y cronología del trabajo seleccionado a la derecha.
    FORM: registro de operaciones maestro-detalle, fiel a la opción visual 2 aprobada.
    """

    refresh_ms = 2000
    colors = {
        "root": "#0b1115",
        "header": "#0a0f13",
        "surface": "#11191e",
        "raised": "#182228",
        "border": "#2b3941",
        "text": "#f2f6f8",
        "muted": "#aebbc2",
        "accent": "#25c5df",
        "accent_dark": "#123649",
        "success": "#42d17d",
        "warning": "#f5ad2d",
        "error": "#ff646d",
    }

    def __init__(self, runtime: OrchestratorRuntime) -> None:
        super().__init__()
        self.runtime = runtime
        self.snapshots = UiSnapshotService(runtime.database)
        self.title("Knowledge Orchestrator")
        self.geometry("1440x900")
        self.minsize(1080, 680)
        self.configure(background=self.colors["root"])

        self._selected_review: ReviewItem | None = None
        self._review_items: dict[str, ReviewItem] = {}
        self._profile_items = {}
        self._selected_profile_id: int | None = None
        self._work_items: dict[str, WorkItem] = {}
        self._selected_work_id: str | None = None
        self._work_filter = "active"
        self._auto_refresh = True
        self._current_page = "work"
        self._refresh_job: str | None = None

        self._configure_style()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind_all("<Control-o>", lambda _event: self._import_documents())
        self.bind_all("<Control-f>", lambda _event: self._focus_search())
        self.bind_all("<F5>", lambda _event: self._refresh(force=True))

    def start(self) -> None:
        self.runtime.start()
        self._refresh(force=True)
        self.mainloop()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Dark.TFrame", background=self.colors["surface"])
        style.configure("Raised.TFrame", background=self.colors["raised"])
        style.configure(
            "Dark.TLabel", background=self.colors["surface"], foreground=self.colors["text"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Muted.TLabel", background=self.colors["surface"], foreground=self.colors["muted"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "Title.TLabel", background=self.colors["surface"], foreground=self.colors["text"],
            font=("Segoe UI Semibold", 18),
        )
        style.configure(
            "Section.TLabel", background=self.colors["surface"], foreground=self.colors["text"],
            font=("Segoe UI Semibold", 11),
        )
        style.configure(
            "Accent.TButton", background=self.colors["accent"], foreground="#061015",
            bordercolor=self.colors["accent"], padding=(16, 9), font=("Segoe UI Semibold", 10),
        )
        style.map("Accent.TButton", background=[("active", "#55d8ea"), ("disabled", "#35515a")])
        style.configure(
            "Secondary.TButton", background=self.colors["raised"], foreground=self.colors["text"],
            bordercolor=self.colors["border"], padding=(14, 9), font=("Segoe UI", 10),
        )
        style.map("Secondary.TButton", background=[("active", "#223038")])
        style.configure(
            "Danger.TButton", background="#311b20", foreground="#ff9aa0",
            bordercolor="#7b3037", padding=(14, 9), font=("Segoe UI", 10),
        )
        style.configure(
            "Dark.TEntry", fieldbackground=self.colors["raised"], foreground=self.colors["text"],
            insertcolor=self.colors["text"], bordercolor=self.colors["border"], padding=8,
        )
        style.configure(
            "Dark.TCombobox", fieldbackground=self.colors["raised"], background=self.colors["raised"],
            foreground=self.colors["text"], arrowcolor=self.colors["muted"], padding=6,
        )
        style.map("Dark.TCombobox", fieldbackground=[("readonly", self.colors["raised"])])
        style.configure(
            "Dark.Treeview", background=self.colors["surface"], fieldbackground=self.colors["surface"],
            foreground=self.colors["text"], bordercolor=self.colors["border"], rowheight=48,
            font=("Segoe UI", 10),
        )
        style.map(
            "Dark.Treeview",
            background=[("selected", self.colors["accent_dark"])],
            foreground=[("selected", self.colors["text"])],
        )
        style.configure(
            "Dark.Treeview.Heading", background=self.colors["raised"], foreground=self.colors["muted"],
            bordercolor=self.colors["border"], padding=(8, 9), font=("Segoe UI Semibold", 9),
        )
        style.map("Dark.Treeview.Heading", background=[("active", "#223038")])
        style.configure(
            "Dark.TCheckbutton", background=self.colors["surface"], foreground=self.colors["text"],
            indicatorbackground=self.colors["raised"], indicatorforeground=self.colors["accent"],
        )

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self._build_header()
        self._build_action_bar()

        self.page_host = tk.Frame(self, bg=self.colors["root"], highlightthickness=0)
        self.page_host.grid(row=2, column=0, sticky="nsew")
        self.page_host.columnconfigure(0, weight=1)
        self.page_host.rowconfigure(0, weight=1)

        self.pages: dict[str, tk.Widget] = {}
        self._build_home()
        self._build_work()
        self._build_review()
        self._build_topics()
        self._build_config()

        footer = tk.Frame(self, bg=self.colors["header"], height=38)
        footer.grid(row=3, column=0, sticky="ew")
        footer.grid_propagate(False)
        footer.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="Arrancando…")
        tk.Label(
            footer, textvariable=self.status_var, bg=self.colors["header"], fg=self.colors["muted"],
            anchor="w", font=("Segoe UI", 9), padx=18,
        ).grid(row=0, column=0, sticky="nsew")
        self.refresh_button = tk.Button(
            footer, text="Pausar actualización", command=self._toggle_refresh, bg=self.colors["header"],
            fg=self.colors["accent"], activebackground=self.colors["raised"],
            activeforeground=self.colors["accent"], relief="flat", borderwidth=0,
            font=("Segoe UI", 9), padx=18, cursor="hand2",
        )
        self.refresh_button.grid(row=0, column=1, sticky="e")
        self._show_page("work")

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=self.colors["header"], height=56)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(1, weight=1)

        brand = tk.Frame(header, bg=self.colors["header"])
        brand.grid(row=0, column=0, sticky="nsw", padx=(20, 54))
        tk.Label(
            brand, text="KO", bg=self.colors["accent"], fg="#061015",
            font=("Segoe UI Semibold", 9), padx=7, pady=6,
        ).pack(side="left", pady=13)
        tk.Label(
            brand, text="Knowledge Orchestrator", bg=self.colors["header"], fg=self.colors["text"],
            font=("Segoe UI Semibold", 12), padx=10,
        ).pack(side="left")

        navigation = tk.Frame(header, bg=self.colors["header"])
        navigation.grid(row=0, column=1, sticky="nsw")
        self.nav_buttons: dict[str, tk.Button] = {}
        for key, label in (
            ("home", "Inicio"), ("work", "Trabajo"), ("review", "Revisión"),
            ("topics", "Temas"), ("config", "Configuración"),
        ):
            button = tk.Button(
                navigation, text=label, command=lambda page=key: self._show_page(page),
                bg=self.colors["header"], fg=self.colors["muted"],
                activebackground=self.colors["raised"], activeforeground=self.colors["text"],
                relief="flat", borderwidth=0, padx=18, pady=16, cursor="hand2",
                font=("Segoe UI", 10),
            )
            button.pack(side="left", fill="y")
            self.nav_buttons[key] = button

    def _build_action_bar(self) -> None:
        bar = tk.Frame(
            self, bg=self.colors["surface"], height=78,
            highlightbackground=self.colors["border"], highlightthickness=1,
        )
        bar.grid(row=1, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.columnconfigure(2, weight=1)
        ttk.Button(bar, text="Importar documentos", style="Accent.TButton", command=self._import_documents).grid(
            row=0, column=0, padx=(20, 10), pady=18
        )
        ttk.Button(bar, text="Abrir carpeta vigilada", style="Secondary.TButton", command=self._open_inbox).grid(
            row=0, column=1, padx=(0, 12), pady=18
        )
        health = tk.Frame(bar, bg=self.colors["surface"])
        health.grid(row=0, column=3, sticky="e", padx=20)
        self.service_var = tk.StringVar(value="Servicio iniciando")
        self.broker_var = tk.StringVar(value="Broker: sin datos")
        self.clock_var = tk.StringVar(value="")
        tk.Label(health, textvariable=self.service_var, bg=self.colors["surface"], fg=self.colors["success"],
                 font=("Segoe UI Semibold", 9)).pack(side="left", padx=(0, 24))
        tk.Label(health, textvariable=self.broker_var, bg=self.colors["surface"], fg=self.colors["accent"],
                 font=("Segoe UI Semibold", 9)).pack(side="left", padx=(0, 24))
        tk.Label(health, textvariable=self.clock_var, bg=self.colors["surface"], fg=self.colors["text"],
                 font=("Segoe UI", 9)).pack(side="left")

    def _new_page(self, name: str) -> tk.Frame:
        page = tk.Frame(self.page_host, bg=self.colors["surface"])
        page.grid(row=0, column=0, sticky="nsew")
        self.pages[name] = page
        return page

    def _build_home(self) -> None:
        page = self._new_page("home")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)
        tk.Label(page, text="Estado del sistema", bg=self.colors["surface"], fg=self.colors["text"],
                 font=("Segoe UI Semibold", 20), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=28, pady=(26, 4)
        )
        tk.Label(
            page, text="Una vista rápida de lo que avanza y de lo que necesita una decisión.",
            bg=self.colors["surface"], fg=self.colors["muted"], font=("Segoe UI", 10), anchor="w",
        ).grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 20))
        metrics = tk.Frame(page, bg=self.colors["surface"])
        metrics.grid(row=2, column=0, sticky="ew", padx=22)
        metrics.columnconfigure((0, 1, 2, 3), weight=1)
        self.dashboard_vars = {
            "active": tk.StringVar(value="0"), "review": tk.StringVar(value="0"),
            "failed": tk.StringVar(value="0"), "published": tk.StringVar(value="0"),
            "broker": tk.StringVar(value="sin datos"), "broker_message": tk.StringVar(value=""),
        }
        for index, (label, key) in enumerate((
            ("En curso", "active"), ("Requieren atención", "failed"),
            ("Pendientes de revisión", "review"), ("Notas publicadas", "published"),
        )):
            card = tk.Frame(metrics, bg=self.colors["raised"], highlightbackground=self.colors["border"], highlightthickness=1)
            card.grid(row=0, column=index, sticky="ew", padx=6, ipady=12)
            tk.Label(card, textvariable=self.dashboard_vars[key], bg=self.colors["raised"], fg=self.colors["text"],
                     font=("Segoe UI Semibold", 22), anchor="w").pack(fill="x", padx=16)
            tk.Label(card, text=label, bg=self.colors["raised"], fg=self.colors["muted"],
                     font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=16)

        attention = tk.Frame(page, bg=self.colors["surface"])
        attention.grid(row=3, column=0, sticky="nsew", padx=28, pady=28)
        attention.columnconfigure(0, weight=1)
        attention.rowconfigure(1, weight=1)
        tk.Label(attention, text="Necesita tu atención", bg=self.colors["surface"], fg=self.colors["text"],
                 font=("Segoe UI Semibold", 12), anchor="w").grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.home_attention = ttk.Treeview(
            attention, columns=("estado", "actualizado"), show="tree headings", style="Dark.Treeview", height=6
        )
        self.home_attention.heading("#0", text="Documento")
        self.home_attention.heading("estado", text="Estado")
        self.home_attention.heading("actualizado", text="Actualizado")
        self.home_attention.column("#0", width=560)
        self.home_attention.column("estado", width=180)
        self.home_attention.column("actualizado", width=120)
        self.home_attention.grid(row=1, column=0, sticky="nsew")
        self.home_attention.bind("<Double-1>", self._open_home_attention)
        ttk.Button(attention, text="Ver todos los trabajos", style="Secondary.TButton",
                   command=lambda: self._show_page("work")).grid(row=2, column=0, sticky="e", pady=(12, 0))

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
        for key, label in (("active", "En curso"), ("attention", "Atención"),
                           ("completed", "Completados"), ("all", "Todos")):
            button = tk.Button(
                filter_row, text=label, command=lambda value=key: self._set_work_filter(value),
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
            search_host, text="Buscar trabajos", bg=self.colors["surface"], fg=self.colors["muted"],
            font=("Segoe UI", 9), padx=0,
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))
        search = ttk.Entry(search_host, textvariable=self.search_var, style="Dark.TEntry")
        search.grid(row=0, column=1, sticky="ew")
        self.search_entry = search
        self.search_entry.insert(0, "")

        self.work_tree = ttk.Treeview(
            left, columns=("estado", "edad", "actualizado"), show="tree headings", style="Dark.Treeview"
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
        self.work_summary_var = tk.StringVar(value="Sin trabajos")
        tk.Label(left, textvariable=self.work_summary_var, bg=self.colors["surface"], fg=self.colors["muted"],
                 font=("Segoe UI", 9), anchor="w", padx=18, pady=12).grid(row=3, column=0, sticky="ew")

        detail_header = tk.Frame(right, bg=self.colors["surface"])
        detail_header.grid(row=0, column=0, sticky="ew", padx=26, pady=(24, 4))
        detail_header.columnconfigure(0, weight=1)
        self.detail_title_var = tk.StringVar(value="Selecciona un trabajo")
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
        self.issue_title_var = tk.StringVar(value="No hay ningún trabajo seleccionado.")
        self.issue_message_var = tk.StringVar(value="Elige un documento de la lista para consultar su estado.")
        tk.Label(self.issue_frame, textvariable=self.issue_title_var, bg=self.colors["raised"], fg=self.colors["text"],
                 font=("Segoe UI Semibold", 11), anchor="w").pack(fill="x", padx=16, pady=(14, 5))
        tk.Label(self.issue_frame, textvariable=self.issue_message_var, bg=self.colors["raised"], fg=self.colors["muted"],
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
        self.retry_button = ttk.Button(action_buttons, text="Reintentar", style="Accent.TButton", command=self._retry_selected)
        self.retry_button.grid(row=0, column=0, sticky="ew", padx=(0, 5), pady=(0, 8))
        self.open_location_button = ttk.Button(
            action_buttons, text="Abrir ubicación", style="Secondary.TButton", command=self._open_selected_location
        )
        self.open_location_button.grid(row=0, column=1, sticky="ew", padx=(5, 0), pady=(0, 8))
        self.ignore_button = ttk.Button(
            action_buttons, text="Ignorar este archivo", style="Danger.TButton", command=self._cancel_or_ignore_selected
        )
        self.ignore_button.grid(row=1, column=0, columnspan=2, sticky="ew")
        for button in (self.retry_button, self.open_location_button, self.ignore_button):
            button.state(["disabled"])

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

    def _build_review(self) -> None:
        page = self._new_page("review")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        self._page_heading(page, "Revisión", "Decide qué cambios semánticos se incorporan a tu base de conocimiento.")
        columns = ("id", "relacion", "confianza", "impacto", "nota", "estado")
        self.review_tree = ttk.Treeview(page, columns=columns, show="headings", height=8, style="Dark.Treeview")
        for column, text in {
            "id": "ID", "relacion": "Relación", "confianza": "Confianza",
            "impacto": "Impacto", "nota": "Nota", "estado": "Estado",
        }.items():
            self.review_tree.heading(column, text=text)
            self.review_tree.column(column, width=120)
        self.review_tree.grid(row=2, column=0, sticky="nsew", padx=24)
        self.review_tree.bind("<<TreeviewSelect>>", lambda _event: self._select_review())
        self.review_detail = tk.Text(page, height=10, wrap="word", bg=self.colors["raised"], fg=self.colors["text"],
                                     insertbackground=self.colors["text"], relief="flat", padx=12, pady=12)
        self.review_detail.grid(row=3, column=0, sticky="ew", padx=24, pady=(12, 0))
        buttons = tk.Frame(page, bg=self.colors["surface"])
        buttons.grid(row=4, column=0, sticky="e", padx=24, pady=16)
        ttk.Button(buttons, text="Aprobar cambio", style="Accent.TButton", command=self._approve_selected).pack(side="left", padx=4)
        ttk.Button(buttons, text="Rechazar", style="Danger.TButton", command=self._reject_selected).pack(side="left", padx=4)

    def _build_topics(self) -> None:
        page = self._new_page("topics")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        self._page_heading(page, "Temas", "Consulta cómo se clasifica y publica el conocimiento.")
        columns = ("pos", "nombre", "carpeta", "perfil", "activo")
        self.topics_tree = ttk.Treeview(page, columns=columns, show="headings", style="Dark.Treeview")
        for column, text in {"pos": "#", "nombre": "Tema", "carpeta": "Carpeta", "perfil": "Perfil", "activo": "Activo"}.items():
            self.topics_tree.heading(column, text=text)
            self.topics_tree.column(column, width=90 if column in {"pos", "activo"} else 260)
        self.topics_tree.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 24))

    def _build_config(self) -> None:
        page = self._new_page("config")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)
        self._page_heading(page, "Configuración", "Ajusta la política aplicada a los trabajos nuevos.")
        self.paths_var = tk.StringVar(value=data_root_label(self.runtime))
        info = tk.Frame(page, bg=self.colors["raised"], highlightbackground=self.colors["border"], highlightthickness=1)
        info.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 14))
        tk.Label(info, text="Raíz de datos", bg=self.colors["raised"], fg=self.colors["muted"],
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))
        tk.Label(info, textvariable=self.paths_var, bg=self.colors["raised"], fg=self.colors["text"],
                 font=("Consolas", 9)).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 8))
        self.capabilities_var = tk.StringVar(value="Esperando negociación con el Broker…")
        tk.Label(info, textvariable=self.capabilities_var, bg=self.colors["raised"], fg=self.colors["muted"],
                 font=("Segoe UI", 9), wraplength=1250, justify="left").grid(
            row=2, column=0, sticky="ew", padx=14, pady=(0, 12)
        )
        info.columnconfigure(0, weight=1)

        content = tk.PanedWindow(page, orient="horizontal", bg=self.colors["border"], sashwidth=2, bd=0)
        content.grid(row=3, column=0, sticky="nsew", padx=24, pady=(0, 24))
        list_frame = tk.Frame(content, bg=self.colors["surface"])
        editor = tk.Frame(content, bg=self.colors["surface"])
        content.add(list_frame, minsize=500, stretch="always")
        content.add(editor, minsize=380, stretch="always")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        columns = ("nombre", "modelo", "estrategia", "datos", "activo")
        self.profiles_tree = ttk.Treeview(list_frame, columns=columns, show="headings", style="Dark.Treeview", height=15)
        for column, text in {"nombre": "Perfil", "modelo": "Modelo", "estrategia": "Estrategia", "datos": "Datos", "activo": "Activo"}.items():
            self.profiles_tree.heading(column, text=text)
            self.profiles_tree.column(column, width=145 if column != "nombre" else 190)
        self.profiles_tree.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.profiles_tree.bind("<<TreeviewSelect>>", lambda _event: self._select_profile())

        self.profile_form = {
            "model": tk.StringVar(value="Automático (Broker)"), "strategy": tk.StringVar(value="single"),
            "classification": tk.StringVar(value="local_only"), "long_context": tk.StringVar(value="fail"),
            "compression": tk.StringVar(value="default del Broker"), "max_cost": tk.StringVar(value="0.05"),
            "human_review": tk.BooleanVar(value=False),
        }
        fields = [
            ("Modelo", "model", ("Automático (Broker)",)),
            ("Estrategia", "strategy", ("single", "mixture_of_agents", "auto")),
            ("Clasificación", "classification", ("public", "internal", "confidential", "local_only")),
            ("Contexto largo", "long_context", ("fail", "map_reduce")),
            ("Compresión", "compression", ("default del Broker", "off", "light", "medium", "aggressive")),
        ]
        self.profile_combos = {}
        for row, (label, key, values) in enumerate(fields):
            tk.Label(editor, text=label, bg=self.colors["surface"], fg=self.colors["muted"],
                     font=("Segoe UI", 9)).grid(row=row, column=0, sticky="w", pady=6)
            combo = ttk.Combobox(editor, textvariable=self.profile_form[key], values=values,
                                 state="readonly", width=27, style="Dark.TCombobox")
            combo.grid(row=row, column=1, sticky="ew", padx=(12, 0), pady=6)
            self.profile_combos[key] = combo
        tk.Label(editor, text="Presupuesto por tarea (USD)", bg=self.colors["surface"], fg=self.colors["muted"],
                 font=("Segoe UI", 9)).grid(row=5, column=0, sticky="w", pady=6)
        ttk.Entry(editor, textvariable=self.profile_form["max_cost"], width=27, style="Dark.TEntry").grid(
            row=5, column=1, sticky="ew", padx=(12, 0), pady=6
        )
        ttk.Checkbutton(editor, text="Exigir revisión humana antes de publicar",
                        variable=self.profile_form["human_review"], style="Dark.TCheckbutton").grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(10, 6)
        )
        tk.Label(
            editor, text="La clasificación controla si el contenido puede salir a la nube. Los cambios solo afectan a tareas nuevas.",
            bg=self.colors["surface"], fg=self.colors["muted"], font=("Segoe UI", 9), wraplength=430,
            justify="left",
        ).grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 14))
        self.save_profile_button = ttk.Button(editor, text="Guardar política", style="Accent.TButton", command=self._save_profile)
        self.save_profile_button.grid(row=8, column=1, sticky="e")
        self.save_profile_button.state(["disabled"])
        editor.columnconfigure(1, weight=1)

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

    def _refresh(self, *, force: bool = False) -> None:
        if self._refresh_job is not None:
            try:
                self.after_cancel(self._refresh_job)
            except tk.TclError:
                pass
            self._refresh_job = None
        self.clock_var.set(datetime.now().strftime("%d %b %Y   %H:%M"))
        if force or self._auto_refresh:
            self._drain_events()
            self._refresh_dashboard()
            self._refresh_work()
            self._refresh_reviews()
            self._refresh_topics()
            self._refresh_profiles()
            self._refresh_capabilities()
        self._refresh_job = self.after(self.refresh_ms, self._refresh_tick)

    def _refresh_tick(self) -> None:
        self._refresh_job = None
        self._refresh()

    def _drain_events(self) -> None:
        events = self.runtime.bridge.drain()
        if events:
            event = events[-1]
            self.status_var.set(event.message)

    def _refresh_dashboard(self) -> None:
        snapshot = self.snapshots.dashboard()
        self.dashboard_vars["active"].set(str(snapshot.active_captures))
        self.dashboard_vars["review"].set(str(snapshot.pending_review))
        self.dashboard_vars["failed"].set(str(snapshot.failed_captures))
        self.dashboard_vars["published"].set(str(snapshot.published_notes))
        self.dashboard_vars["broker"].set(snapshot.broker_status)
        self.dashboard_vars["broker_message"].set(snapshot.broker_message)
        self.service_var.set("Servicio activo")
        self.broker_var.set(f"Broker: {'Conectado' if snapshot.broker_status == 'online' else snapshot.broker_status}")

    def _refresh_work(self) -> None:
        items = self.snapshots.work_items()
        self._work_items = {item.capture_id: item for item in items}
        self._refresh_work_list()
        attention = [item for item in items if item.category == "attention"]
        self.dashboard_vars["failed"].set(str(len(attention)))
        self._replace_tree(
            self.home_attention,
            [(item.capture_id, (item.status_label, item.updated_label)) for item in attention[:8]],
            texts={item.capture_id: self._work_row_text(item) for item in attention[:8]},
            tags={item.capture_id: ("attention",) for item in attention[:8]},
        )

    def _refresh_work_list(self) -> None:
        if not hasattr(self, "work_tree"):
            return
        items = list(self._work_items.values())
        counts = {
            "active": sum(item.category == "active" for item in items),
            "attention": sum(item.category == "attention" for item in items),
            "completed": sum(item.category == "completed" for item in items),
            "all": len(items),
        }
        labels = {"active": "En curso", "attention": "Atención", "completed": "Completados", "all": "Todos"}
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
            f"Mostrando {len(visible)} de {len(items)} trabajos"
            if items else "Aún no hay trabajos. Importa un documento para empezar."
        )
        visible_ids = {item.capture_id for item in visible}
        if self._selected_work_id in visible_ids:
            self.work_tree.selection_set(self._selected_work_id)
            self.work_tree.see(self._selected_work_id)
            self._render_work_detail(self._work_items[self._selected_work_id])
        elif visible:
            self.work_tree.selection_set(visible[0].capture_id)
            self._selected_work_id = visible[0].capture_id
            self._render_work_detail(visible[0])
        else:
            self._selected_work_id = None
            self._render_empty_detail()

    def _set_work_filter(self, value: str) -> None:
        self._work_filter = value
        self._refresh_work_list()

    def _select_work(self) -> None:
        selection = self.work_tree.selection()
        if not selection:
            return
        self._selected_work_id = str(selection[0])
        item = self._work_items.get(self._selected_work_id)
        if item:
            self._render_work_detail(item)

    def _render_work_detail(self, item: WorkItem) -> None:
        self.detail_title_var.set(item.title)
        self.detail_badge_var.set(item.status_label)
        self.detail_path_var.set(item.path or item.filename)
        self.detail_id_var.set(
            f"ID de incidencia: {item.incident_id}"
            if item.incident_id is not None
            else f"ID de captura: {item.capture_id}"
        )
        badge_colors = {
            "attention": ("#311b20", self.colors["error"]),
            "completed": ("#173123", self.colors["success"]),
            "active": (self.colors["accent_dark"], self.colors["accent"]),
        }
        background, foreground = badge_colors[item.category]
        self.detail_badge.configure(bg=background, fg=foreground)

        if item.category == "attention":
            self.issue_title_var.set("No se pudo completar el trabajo.")
            recovery = item.error_message or "Revisa el detalle técnico y vuelve a intentarlo cuando la causa esté resuelta."
            self.issue_message_var.set(f"{recovery}\n\nTu archivo original se conserva; esta acción no modifica su contenido.")
        elif item.category == "completed":
            self.issue_title_var.set("Trabajo completado.")
            self.issue_message_var.set("El documento terminó el flujo y su historial permanece disponible.")
        else:
            self.issue_title_var.set("El documento sigue avanzando.")
            self.issue_message_var.set(item.progress_text or f"Fase actual: {item.phase}. La vista se actualiza automáticamente.")

        events = self.snapshots.work_events(item.capture_id)
        self.timeline.configure(state="normal")
        self.timeline.delete("1.0", "end")
        if not events:
            self.timeline.insert("end", "Todavía no hay eventos registrados para este trabajo.")
        else:
            for event in events:
                self.timeline.insert("end", f"{event.created_label}   ", "time")
                self.timeline.insert("end", f"{self._event_label(event.event_type)}\n", "event")
                self.timeline.insert("end", f"             {event.message}\n\n")
        self.timeline.configure(state="disabled")

        self.technical_var.set(
            f"Detalles técnicos: estado={item.status} · fase={item.phase} · modelo={item.model} "
            f"· intentos={item.attempt} · código={item.error_code or '—'}"
        )
        self.open_location_button.state(["!disabled"] if item.path else ["disabled"])
        can_retry = item.category == "attention" and (
            (bool(item.task_id) and item.status == "ERROR") or item.incident_id is not None
        )
        self.retry_button.state(["!disabled"] if can_retry else ["disabled"])
        if item.category == "active" and item.task_id and item.status in {"QUEUED", "PROCESSING"}:
            self.ignore_button.configure(text="Cancelar tarea")
            self.ignore_button.state(["!disabled"])
        elif item.category == "attention" and item.status in {"ERROR", "INGESTION_ERROR"}:
            self.ignore_button.configure(text="Ignorar este archivo")
            self.ignore_button.state(["!disabled"])
        else:
            self.ignore_button.configure(text="Ignorar este archivo")
            self.ignore_button.state(["disabled"])

    def _render_empty_detail(self) -> None:
        self.detail_title_var.set("Selecciona un trabajo")
        self.detail_badge_var.set("")
        self.detail_path_var.set("El detalle aparecerá aquí.")
        self.detail_id_var.set("")
        self.issue_title_var.set("No hay trabajos en esta vista.")
        self.issue_message_var.set("Cambia el filtro, limpia la búsqueda o importa un documento para empezar.")
        self.timeline.configure(state="normal")
        self.timeline.delete("1.0", "end")
        self.timeline.configure(state="disabled")
        self.technical_var.set("Detalles técnicos: —")
        for button in (self.retry_button, self.open_location_button, self.ignore_button):
            button.state(["disabled"])

    def _import_documents(self) -> None:
        selected = filedialog.askopenfilenames(
            parent=self, title="Importar documentos", filetypes=(("Documentos Markdown", "*.md"),)
        )
        if not selected:
            return
        self.runtime.paths.inbox.mkdir(parents=True, exist_ok=True)
        imported = 0
        failures: list[str] = []
        for raw_path in selected:
            source = Path(raw_path)
            try:
                target = self._available_inbox_path(source.name)
                if source.resolve() != target.resolve():
                    shutil.copy2(source, target)
                if self.runtime.ingestion_worker.submit(target):
                    imported += 1
            except OSError as error:
                failures.append(f"{source.name}: {error}")
        if failures:
            messagebox.showerror("Algunos documentos no se importaron", "\n".join(failures[:6]), parent=self)
        self.status_var.set(
            f"{imported} documento{'s' if imported != 1 else ''} añadido{'s' if imported != 1 else ''} a la carpeta vigilada."
        )
        self._show_page("work")
        self._work_filter = "active"
        self.after(250, lambda: self._refresh(force=True))

    def _available_inbox_path(self, filename: str) -> Path:
        candidate = self.runtime.paths.inbox / filename
        if not candidate.exists():
            return candidate
        stem, suffix = candidate.stem, candidate.suffix
        index = 2
        while True:
            alternative = candidate.with_name(f"{stem} ({index}){suffix}")
            if not alternative.exists():
                return alternative
            index += 1

    def _open_inbox(self) -> None:
        self.runtime.paths.inbox.mkdir(parents=True, exist_ok=True)
        self._open_path(self.runtime.paths.inbox)

    def _open_selected_location(self) -> None:
        item = self._selected_item()
        if not item or not item.path:
            return
        path = Path(item.path)
        target = path if path.is_dir() else path.parent
        if not target.exists():
            messagebox.showinfo("Ubicación no disponible", "El archivo ya no está en esa ubicación.", parent=self)
            return
        self._open_path(target)

    def _open_path(self, path: Path) -> None:
        try:
            os.startfile(str(path))
        except OSError as error:
            messagebox.showerror("No se pudo abrir la ubicación", str(error), parent=self)

    def _retry_selected(self) -> None:
        item = self._selected_item()
        if not item:
            return
        if item.incident_id is not None:
            path = Path(item.path)
            if not path.exists():
                messagebox.showinfo(
                    "El archivo ya no está disponible",
                    "Vuelve a importarlo o cópialo de nuevo a la carpeta vigilada.",
                    parent=self,
                )
                return
            changed = self.runtime.ingestion_worker.retry(path)
        elif item.task_id:
            changed = self.runtime.workflow_repository.retry_failed_task(item.task_id)
        else:
            changed = False
        if changed:
            self.status_var.set(f"Reintento solicitado para {item.title}.")
            self._work_filter = "active"
            self._refresh(force=True)
        else:
            messagebox.showinfo("El estado cambió", "La tarea ya no está fallida. La lista se actualizará.", parent=self)
            self._refresh(force=True)

    def _cancel_or_ignore_selected(self) -> None:
        item = self._selected_item()
        if not item:
            return
        if item.category == "active" and item.task_id:
            if not messagebox.askyesno("Cancelar tarea", "La tarea dejará de ejecutarse. ¿Continuar?", parent=self):
                return
            changed = self.runtime.broker_worker.request_cancel(item.task_id)
            message = "Cancelación solicitada." if changed else "La tarea ya cambió de estado."
        else:
            if not messagebox.askyesno(
                "Ignorar incidencia",
                "El trabajo se marcará como cancelado, pero se conservarán el archivo y el historial. ¿Continuar?",
                parent=self,
            ):
                return
            changed = (
                self.runtime.repository.ignore_ingestion_incident(item.incident_id)
                if item.incident_id is not None
                else self.runtime.workflow_repository.ignore_failed_capture(item.capture_id)
            )
            message = "Incidencia cerrada; el historial se conserva." if changed else "El trabajo ya cambió de estado."
        self.status_var.set(message)
        self._refresh(force=True)

    def _selected_item(self) -> WorkItem | None:
        return self._work_items.get(self._selected_work_id or "")

    def _open_home_attention(self, _event: tk.Event) -> None:
        selection = self.home_attention.selection()
        if not selection:
            return
        self._work_filter = "attention"
        self._selected_work_id = str(selection[0])
        self._show_page("work")
        self._refresh_work_list()

    def _focus_search(self) -> None:
        self._show_page("work")
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, "end")

    def _toggle_refresh(self) -> None:
        self._auto_refresh = not self._auto_refresh
        self.refresh_button.configure(text="Pausar actualización" if self._auto_refresh else "Reanudar actualización")
        self.status_var.set("Actualización automática activa." if self._auto_refresh else "Actualización automática en pausa.")
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

    def _refresh_reviews(self) -> None:
        items = self.snapshots.reviews()
        self._review_items = {str(item.candidate_id): item for item in items}
        self._replace_tree(
            self.review_tree,
            [(str(item.candidate_id), (item.candidate_id, item.relation,
              "" if item.confidence is None else f"{item.confidence:.2f}", item.impact,
              item.target_note_id, item.status)) for item in items],
        )

    def _refresh_topics(self) -> None:
        self._replace_tree(
            self.topics_tree,
            [(str(item.topic_id), (item.position, item.name, item.folder, item.default_profile,
              "sí" if item.enabled else "no")) for item in self.snapshots.topics()],
        )

    def _refresh_profiles(self) -> None:
        profiles = self.snapshots.profiles()
        self._profile_items = {item.profile_id: item for item in profiles}
        self._replace_tree(
            self.profiles_tree,
            [(str(item.profile_id), (item.name, item.preferred_model or "Automático",
              item.execution_strategy, item.data_classification, "sí" if item.enabled else "no"))
             for item in profiles],
        )

    def _refresh_capabilities(self) -> None:
        capabilities = self.runtime.broker_worker.capabilities_snapshot()
        strategies = available_profile_strategies(capabilities)
        self.profile_combos["strategy"].configure(values=strategies)
        self.profile_combos["long_context"].configure(
            values=("fail", "map_reduce") if not capabilities or capabilities.get("long_context_map_reduce") else ("fail",)
        )
        if not capabilities:
            self.capabilities_var.set("No hay capacidades publicadas. El Broker validará las peticiones nuevas.")
            return
        lanes = ", ".join(capabilities.get("work_lanes") or ["inference"])
        self.capabilities_var.set(
            f"Contrato {capabilities.get('contract_version', '?')} · Carriles: {lanes} · "
            f"Estrategias: {', '.join(strategies)}"
        )

    def _select_profile(self) -> None:
        selection = self.profiles_tree.selection()
        if not selection:
            return
        profile_id = int(selection[0])
        item = self._profile_items.get(profile_id)
        if item is None:
            return
        self._selected_profile_id = profile_id
        models = ["Automático (Broker)", *self.snapshots.model_names()]
        if item.preferred_model and item.preferred_model not in models:
            models.append(item.preferred_model)
        self.profile_combos["model"].configure(values=models)
        self.profile_form["model"].set(item.preferred_model or "Automático (Broker)")
        self.profile_form["strategy"].set(item.execution_strategy)
        self.profile_form["classification"].set(item.data_classification)
        self.profile_form["long_context"].set(item.long_context)
        self.profile_form["compression"].set(item.prompt_compression or "default del Broker")
        self.profile_form["max_cost"].set(str(item.max_cost_usd))
        self.profile_form["human_review"].set(item.human_review_required)
        self.save_profile_button.state(["!disabled"])

    def _save_profile(self) -> None:
        if self._selected_profile_id is None:
            return
        try:
            max_cost = float(self.profile_form["max_cost"].get())
            current = self.runtime.profiles.get_profile(self._selected_profile_id)
            capabilities = self.runtime.broker_worker.capabilities_snapshot()
            strategy = self.profile_form["strategy"].get()
            if capabilities and strategy not in available_profile_strategies(capabilities):
                raise ValueError(f"El Broker actual no ofrece la estrategia {strategy}")
            long_context = self.profile_form["long_context"].get()
            if long_context == "map_reduce" and capabilities and not capabilities.get("long_context_map_reduce"):
                raise ValueError("El Broker actual no ofrece map_reduce")
            updated = replace(
                current,
                preferred_model="" if self.profile_form["model"].get() == "Automático (Broker)" else self.profile_form["model"].get(),
                execution_strategy=strategy,
                data_classification=self.profile_form["classification"].get(),
                long_context=long_context,
                prompt_compression=None if self.profile_form["compression"].get() == "default del Broker" else self.profile_form["compression"].get(),
                max_cost_usd=max_cost,
                human_review_required=bool(self.profile_form["human_review"].get()),
            )
            saved = self.runtime.profiles.save_profile(updated)
        except (TypeError, ValueError, RuntimeError) as error:
            messagebox.showerror("No se pudo guardar la política", str(error), parent=self)
            return
        self.status_var.set(f"Perfil {saved.name} actualizado. La política se aplicará a las tareas nuevas.")
        self._refresh_profiles()

    def _select_review(self) -> None:
        selection = self.review_tree.selection()
        if not selection:
            return
        item = self._review_items.get(str(selection[0]))
        if item is None:
            return
        self._selected_review = item
        self.review_detail.configure(state="normal")
        self.review_detail.delete("1.0", "end")
        self.review_detail.insert(
            "1.0", f"Motivo:\n{item.rationale}\n\nCambio propuesto:\n{item.diff_text}\n\nBloqueo: {item.blocked_reason or '—'}"
        )
        self.review_detail.configure(state="disabled")

    def _approve_selected(self) -> None:
        if not self._selected_review:
            return
        try:
            self.runtime.semantic_maintenance.approve(self._selected_review.candidate_id)
        except Exception as error:
            messagebox.showerror("No se pudo aprobar", str(error), parent=self)
        else:
            self.status_var.set(f"Candidato {self._selected_review.candidate_id} aprobado.")
            self._selected_review = None
            self._refresh_reviews()

    def _reject_selected(self) -> None:
        if not self._selected_review:
            return
        try:
            self.runtime.semantic_maintenance.reject(self._selected_review.candidate_id)
        except Exception as error:
            messagebox.showerror("No se pudo rechazar", str(error), parent=self)
        else:
            self.status_var.set(f"Candidato {self._selected_review.candidate_id} rechazado.")
            self._selected_review = None
            self._refresh_reviews()

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
            options = {"values": values}
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
        if self._refresh_job is not None:
            try:
                self.after_cancel(self._refresh_job)
            except tk.TclError:
                pass
            self._refresh_job = None
        try:
            self.runtime.stop()
        finally:
            self.destroy()


def run_dashboard(runtime: OrchestratorRuntime) -> None:
    OrchestratorDashboard(runtime).start()


def data_root_label(runtime: OrchestratorRuntime) -> str:
    """Devuelve una raíz humana estable aunque PipelinePaths no exponga `root`."""
    paths = runtime.paths
    if paths.state.name == "state":
        return str(paths.state.parent)
    return str(paths.state)


def available_profile_strategies(capabilities: dict) -> tuple[str, ...]:
    offered = capabilities.get("strategies")
    if not isinstance(offered, list):
        return ("single", "mixture_of_agents", "auto")
    allowed = tuple(strategy for strategy in ("single", "mixture_of_agents", "auto") if strategy in offered)
    return allowed or ("single",)
