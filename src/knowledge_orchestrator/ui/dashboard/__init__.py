"""Interfaz de operaciones de Knowledge Orchestrator.

THESIS: el trabajo activo es el producto; se rechaza la cuadrícula de métricas
como pantalla principal.
OWN-WORLD: superficies grafito, divisores precisos, texto claro y cian reservado
para acción, selección y actividad.
STORY: el usuario ve qué documentos avanzan, detecta qué requiere atención y actúa.
FIRST VIEWPORT: navegación y acciones arriba; lista filtrable a la izquierda;
diagnóstico y cronología del trabajo seleccionado a la derecha.
FORM: registro de operaciones maestro-detalle, fiel a la opción visual 2 aprobada.

El panel está partido por pantalla, que es como se piensa y como se cambia:

- `estilo`            — paleta y estilos ttk.
- `base`              — estado, páginas y utilidades compartidas.
- `inicio`            — vista «Inicio».
- `trabajo`           — vista «Trabajo»: lista, filtros y selección.
- `trabajo_detalle`   — el panel derecho de esa vista.
- `trabajo_acciones`  — importar, abrir, reintentar, ignorar.
- `revision`          — vista «Revisión».
- `temas`             — vista «Temas».
- `configuracion`     — vista «Configuración».

Este módulo es el ensamblaje: monta la cabecera, la barra de acciones y el pie,
y coordina el ciclo de refresco. Todo lo que el resto del proyecto necesita del
panel entra por aquí.
"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from functools import partial
from tkinter import ttk

from knowledge_orchestrator import __version__
from knowledge_orchestrator.runtime import OrchestratorRuntime
from knowledge_orchestrator.ui.dashboard.configuracion import (
    ConfiguracionMixin,
    available_profile_strategies,
    data_root_label,
)

__all__ = [
    "OrchestratorDashboard",
    "available_profile_strategies",
    "data_root_label",
    "run_dashboard",
]


class OrchestratorDashboard(ConfiguracionMixin):
    """La ventana completa: cabecera, barra de acciones, páginas y pie."""

    def __init__(self, runtime: OrchestratorRuntime) -> None:
        super().__init__(runtime)
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

    # ---------------------------------------------------------- construcción

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self._build_header()
        self._build_action_bar()

        self.page_host = tk.Frame(self, bg=self.colors["root"], highlightthickness=0)
        self.page_host.grid(row=2, column=0, sticky="nsew")
        self.page_host.columnconfigure(0, weight=1)
        self.page_host.rowconfigure(0, weight=1)

        self.pages = {}
        self._build_home()
        self._build_work()
        self._build_review()
        self._build_topics()
        self._build_config()

        self._build_footer()
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
        # La versión en pantalla: al reportar un fallo hace falta saber
        # contra qué build se está mirando, sin abrir un fichero.
        tk.Label(
            brand, text=f"v{__version__}", bg=self.colors["header"], fg=self.colors["muted"],
            font=("Segoe UI", 9),
        ).pack(side="left", padx=(2, 0))

        navigation = tk.Frame(header, bg=self.colors["header"])
        navigation.grid(row=0, column=1, sticky="nsw")
        self.nav_buttons = {}
        for key, label in (
            ("home", "Inicio"), ("work", "Trabajo"), ("review", "Revisión"),
            ("topics", "Temas"), ("config", "Configuración"),
        ):
            button = tk.Button(
                navigation, text=label, command=partial(self._show_page, key),
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

    def _build_footer(self) -> None:
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

    # -------------------------------------------------------------- refresco

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


def run_dashboard(runtime: OrchestratorRuntime) -> None:
    OrchestratorDashboard(runtime).start()
