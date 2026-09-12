"""Interfaz de Knowledge Orchestrator: centro documental con IA.

THESIS: el trabajo activo es el producto; se rechaza la cuadrícula de métricas
como pantalla principal.
OWN-WORLD: superficies grafito, divisores precisos, texto claro y cian reservado
para acción, selección y actividad.
STORY: el usuario ve qué documentos avanzan, detecta qué requiere atención y actúa.
FIRST VIEWPORT: navegación lateral agrupada por intención (trabajo, conocimiento,
sistema) con contadores; a la derecha, la vista activa.
FORM: centro documental con registros maestro-detalle donde la tarea lo exige.

La navegación era una fila de diez pestañas del mismo peso: lo diario
(Documentos, Revisión) competía con la administración (Servicios,
Organización). La barra lateral agrupa por intención y los contadores dicen
dónde hace falta entrar sin abrir cada pantalla.

El panel está partido por pantalla, que es como se piensa y como se cambia:

- `estilo`            — paleta, iconos, estilos ttk y piezas visuales.
- `base`              — estado, páginas y utilidades compartidas.
- `inicio`            — vista «Inicio».
- `trabajo`           — vista «Documentos»: lista, filtros y selección.
- `trabajo_detalle`   — el panel derecho de esa vista.
- `trabajo_acciones`  — importar, abrir, reintentar, ignorar.
- `biblioteca`        — conocimiento publicado en los vaults.
- `revision`          — vista «Revisión».
- `temas`             — vista «Organización».
- `configuracion`     — vista «Ajustes».

Este módulo es el ensamblaje: monta la barra lateral y el pie, y coordina el
ciclo de refresco. Todo lo que el resto del proyecto necesita del panel entra
por aquí.
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from tkinter import messagebox, ttk

from knowledge_orchestrator import __version__
from knowledge_orchestrator.runtime import OrchestratorRuntime
from knowledge_orchestrator.ui.dashboard.configuracion import (
    available_profile_strategies,
    data_root_label,
)
from knowledge_orchestrator.ui.dashboard.estilo import FONT, FONT_SEMIBOLD, ICON_FONT, ICONS, TONES
from knowledge_orchestrator.ui.dashboard.servicios import ServiciosMixin

__all__ = [
    "NAVIGATION",
    "OrchestratorDashboard",
    "available_profile_strategies",
    "data_root_label",
    "run_dashboard",
]

#: Sección -> (clave de página, rótulo, icono). Las claves no cambian: son el
#: contrato con el resto del panel y con las pruebas.
NAVIGATION: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...] = (
    ("TRABAJO", (
        ("home", "Inicio", "home"),
        ("work", "Documentos", "document"),
        ("review", "Revisión", "review"),
    )),
    ("CONOCIMIENTO", (
        ("library", "Biblioteca", "library"),
        ("knowledge", "Afirmaciones", "claims"),
        ("sources", "Fuentes", "sources"),
    )),
    ("SISTEMA", (
        ("operations", "Actividad", "activity"),
        ("services", "Automatización y API", "automation"),
        ("topics", "Organización", "folder"),
        ("config", "Ajustes", "settings"),
    )),
)
SIDEBAR_WIDTH = 236


@dataclass(frozen=True, slots=True)
class NavParts:
    """Piezas de una entrada de navegación que cambian al seleccionarla."""

    marker: tk.Frame
    glyph: tk.Label
    text: tk.Label
    badge: tk.Label


class OrchestratorDashboard(ServiciosMixin):
    """La ventana completa: barra lateral, páginas y pie."""

    def __init__(self, runtime: OrchestratorRuntime) -> None:
        super().__init__(runtime)
        self._configure_style()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind_all("<Control-o>", lambda _event: self._import_documents())
        self.bind_all("<Control-f>", lambda _event: self._focus_search())
        self.bind_all("<F5>", lambda _event: self._refresh(force=True))
        # Ctrl+1 … Ctrl+0 recorren la navegación en el orden en que se ve.
        order = [key for _section, entries in NAVIGATION for key, _label, _icon in entries]
        for index, key in enumerate(order[:10]):
            digit = str((index + 1) % 10)
            self.bind_all(f"<Control-Key-{digit}>", partial(self._show_page_event, key))

    def start(self) -> None:
        self.status_var.set("Preparando documentos en segundo plano…")
        self._startup.start()
        self.after(50, self._finish_startup)
        self.mainloop()

    def _finish_startup(self) -> None:
        if not self._startup.done:
            self.after(50, self._finish_startup)
            return
        if self._startup.error is not None:
            self.status_var.set(f"No se pudo iniciar el servicio: {self._startup.error}")
            messagebox.showerror("No se pudo iniciar Knowledge Orchestrator", str(self._startup.error), parent=self)
            return
        self.status_var.set("Servicio listo. La vista se actualiza sola cada 2 segundos.")
        self._refresh(force=True)

    # ---------------------------------------------------------- construcción

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self._build_sidebar()

        main = tk.Frame(self, bg=self.colors["surface"], highlightthickness=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)
        self.page_host = tk.Frame(main, bg=self.colors["root"], highlightthickness=0)
        self.page_host.grid(row=0, column=0, sticky="nsew")
        self.page_host.columnconfigure(0, weight=1)
        self.page_host.rowconfigure(0, weight=1)

        self.pages = {}
        self._build_home()
        self._build_work()
        self._build_library()
        self._build_review()
        self._build_topics()
        self._build_config()
        self._build_sources()
        self._build_knowledge()
        self._build_operations()
        self._build_services()

        self._build_footer(main)
        self._show_page("home")

    def _build_sidebar(self) -> None:
        c = self.colors
        bar = tk.Frame(self, bg=c["sidebar"], width=SIDEBAR_WIDTH, highlightthickness=0)
        bar.grid(row=0, column=0, sticky="nsw")
        bar.pack_propagate(False)
        tk.Frame(bar, bg=c["border"], width=1).pack(side="right", fill="y")

        brand = tk.Frame(bar, bg=c["sidebar"])
        brand.pack(fill="x", padx=18, pady=(18, 16))
        tk.Label(
            brand, text="KO", bg=c["sidebar"], fg=c["accent"], font=(FONT_SEMIBOLD, 14), padx=7, pady=3,
            highlightbackground=c["accent"], highlightthickness=1,
        ).pack(side="left")
        names = tk.Frame(brand, bg=c["sidebar"])
        names.pack(side="left", padx=(10, 0))
        tk.Label(names, text="Knowledge\nOrchestrator", bg=c["sidebar"], fg=c["text"],
                 font=(FONT_SEMIBOLD, 10), anchor="w", justify="left").pack(fill="x")
        # La versión en pantalla: al reportar un fallo hace falta saber
        # contra qué build se está mirando, sin abrir un fichero.
        tk.Label(names, text=f"v{__version__}", bg=c["sidebar"], fg=c["faint"],
                 font=(FONT, 9), anchor="w").pack(fill="x")

        ttk.Button(bar, text="+   Importar documentos", style="Accent.TButton",
                   command=self._import_documents).pack(fill="x", padx=16)
        tk.Button(
            bar, text="Abrir carpeta vigilada", command=self._open_inbox, bg=c["sidebar"], fg=c["muted"],
            activebackground=c["sidebar"], activeforeground=c["accent"], relief="flat", bd=0,
            font=(FONT, 9), cursor="hand2", anchor="w",
        ).pack(fill="x", padx=18, pady=(8, 4))

        self.nav_buttons = {}
        self._nav_parts: dict[str, NavParts] = {}
        for index, (section, entries) in enumerate(NAVIGATION):
            tk.Label(bar, text=section, bg=c["sidebar"], fg=c["faint"], font=(FONT_SEMIBOLD, 8),
                     anchor="w").pack(fill="x", padx=22, pady=(16 if index else 12, 4))
            for key, label, icon in entries:
                self._nav_item(bar, key, label, icon)

        health = tk.Frame(bar, bg=c["sidebar"])
        health.pack(side="bottom", fill="x", padx=18, pady=(10, 16))
        tk.Frame(bar, bg=c["border"], height=1).pack(side="bottom", fill="x")
        self.service_var = tk.StringVar(value="Servicio iniciando")
        self.broker_var = tk.StringVar(value="Broker: sin datos")
        self.clock_var = tk.StringVar(value="")
        rows = []
        for variable in (self.service_var, self.broker_var):
            row = tk.Frame(health, bg=c["sidebar"])
            row.pack(fill="x", pady=2)
            dot = tk.Label(row, text="●", bg=c["sidebar"], fg=c["faint"], font=(FONT, 9))
            dot.pack(side="left")
            tk.Label(row, textvariable=variable, bg=c["sidebar"], fg=c["muted"], font=(FONT, 9),
                     anchor="w").pack(side="left", padx=(6, 0))
            rows.append(dot)
        self.service_dot, self.broker_dot = rows
        tk.Label(health, textvariable=self.clock_var, bg=c["sidebar"], fg=c["faint"], font=(FONT, 8),
                 anchor="w").pack(fill="x", pady=(6, 0))

    def _nav_item(self, parent: tk.Frame, key: str, label: str, icon: str) -> None:
        c = self.colors
        item = tk.Frame(parent, bg=c["sidebar"], cursor="hand2", takefocus=1, highlightthickness=1,
                        highlightbackground=c["sidebar"], highlightcolor=c["accent"])
        item.pack(fill="x", padx=10, pady=1)
        marker = tk.Frame(item, bg=c["sidebar"], width=3)
        marker.pack(side="left", fill="y")
        glyph = tk.Label(item, text=ICONS[icon], bg=c["sidebar"], fg=c["muted"], font=(ICON_FONT, 12), width=2)
        glyph.pack(side="left", padx=(9, 8), pady=7)
        text = tk.Label(item, text=label, bg=c["sidebar"], fg=c["muted"], font=(FONT, 10), anchor="w")
        text.pack(side="left", fill="x", expand=True)
        badge = tk.Label(item, text="", font=(FONT_SEMIBOLD, 8), padx=6, pady=0, bd=0)
        for widget in (item, marker, glyph, text, badge):
            widget.bind("<Button-1>", partial(self._show_page_event, key))
            widget.bind("<Enter>", partial(self._hover_nav, key, True))
            widget.bind("<Leave>", partial(self._hover_nav, key, False))
        item.bind("<Return>", partial(self._show_page_event, key))
        item.bind("<space>", partial(self._show_page_event, key))
        self.nav_buttons[key] = item
        self._nav_parts[key] = NavParts(marker=marker, glyph=glyph, text=text, badge=badge)

    def _paint_navigation(self, page: str) -> None:
        c = self.colors
        for key, item in self.nav_buttons.items():
            parts = self._nav_parts[key]
            selected = key == page
            background = c["raised"] if selected else c["sidebar"]
            item.configure(bg=background)
            parts.marker.configure(bg=c["accent"] if selected else background)
            parts.glyph.configure(bg=background, fg=c["accent"] if selected else c["muted"])
            parts.text.configure(bg=background, fg=c["text"] if selected else c["muted"],
                                 font=(FONT_SEMIBOLD if selected else FONT, 10))

    def _hover_nav(self, key: str, inside: bool, _event: object = None) -> None:
        if key == self._current_page:
            return
        background = self.colors["hover"] if inside else self.colors["sidebar"]
        parts = self._nav_parts[key]
        for widget in (self.nav_buttons[key], parts.marker, parts.glyph, parts.text):
            widget.configure(bg=background)

    def _set_nav_badge(self, key: str, count: int, tone: str) -> None:
        badge = self._nav_parts[key].badge
        if count <= 0:
            badge.pack_forget()
            return
        badge.configure(text=str(count), bg=TONES[tone][1], fg="#0b1115")
        if not badge.winfo_ismapped():
            badge.pack(side="right", padx=(4, 10))

    def _sync_navigation_badges(self) -> None:
        def count(key: str) -> int:
            try:
                return int(self.dashboard_vars[key].get())
            except ValueError:
                return 0

        self._set_nav_badge("work", count("failed"), "error")
        self._set_nav_badge("review", count("review"), "warning")

    def _build_footer(self, parent: tk.Frame) -> None:
        c = self.colors
        footer = tk.Frame(parent, bg=c["sidebar"], height=34)
        footer.grid(row=1, column=0, sticky="ew")
        footer.grid_propagate(False)
        footer.columnconfigure(1, weight=1)
        footer.rowconfigure(0, weight=1)
        tk.Label(footer, text=ICONS["info"], bg=c["sidebar"], fg=c["faint"],
                 font=(ICON_FONT, 9)).grid(row=0, column=0, padx=(18, 8))
        self.status_var = tk.StringVar(value="Arrancando…")
        tk.Label(
            footer, textvariable=self.status_var, bg=c["sidebar"], fg=c["muted"], anchor="w", font=(FONT, 9),
        ).grid(row=0, column=1, sticky="nsew")
        self.refresh_button = tk.Button(
            footer, text="Pausar actualización", command=self._toggle_refresh, bg=c["sidebar"],
            fg=c["accent"], activebackground=c["raised"], activeforeground=c["accent"], relief="flat",
            borderwidth=0, font=(FONT, 9), padx=18, cursor="hand2",
        )
        self.refresh_button.grid(row=0, column=2, sticky="nse")

    # -------------------------------------------------------------- refresco

    def _refresh(self, *, force: bool = False) -> None:
        if self._refresh_job is not None:
            try:
                self.after_cancel(self._refresh_job)
            except tk.TclError:
                pass
            self._refresh_job = None
        self.clock_var.set(datetime.now().strftime("%d/%m/%Y · %H:%M"))
        if force or self._auto_refresh:
            self._drain_events()
            self._refresh_dashboard()
            self._refresh_work()
            if self._current_page == "library":
                self._refresh_library()
            if self._current_page == "sources":
                self._refresh_sources()
            if self._current_page == 'knowledge':
                self._refresh_knowledge()
            if self._current_page == 'operations':
                self._refresh_flow()
            if self._current_page == 'services':
                self._refresh_services()
            self._refresh_reviews()
            self._refresh_topics()
            self._refresh_profiles()
            self._refresh_capabilities()
            self._sync_navigation_badges()
        self._refresh_job = self.after(self.refresh_ms, self._refresh_tick)

    def _refresh_tick(self) -> None:
        self._refresh_job = None
        self._refresh()


def run_dashboard(runtime: OrchestratorRuntime) -> None:
    OrchestratorDashboard(runtime).start()
