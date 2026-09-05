"""Vista «Inicio»: el estado del sistema de un vistazo.

STORY: el usuario ve qué documentos avanzan y detecta qué requiere atención.
Las tarjetas son un resumen, no el producto: doble clic en una fila lleva al
trabajo concreto, que es donde se actúa.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from knowledge_orchestrator.ui.dashboard.base import DashboardBase


class InicioMixin(DashboardBase):
    """Tarjetas de estado y lista de lo que necesita una decisión."""

    def _build_home(self) -> None:
        page = self._new_page("home")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(4, weight=1)
        tk.Label(page, text="Resumen documental", bg=self.colors["surface"], fg=self.colors["text"],
                 font=("Segoe UI Semibold", 20), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=28, pady=(26, 4)
        )
        tk.Label(
            page, text="Qué está pasando, qué necesita una decisión y cuánto conocimiento está disponible.",
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
        self.dashboard_card_vars = {
            key: tk.StringVar(value=f"0\n{label}")
            for label, key in (
                ("En proceso", "active"), ("Necesitan atención", "failed"),
                ("Decisiones pendientes", "review"), ("En la biblioteca", "published"),
            )
        }
        card_actions = {
            "active": lambda: self._open_document_filter("active"),
            "failed": lambda: self._open_document_filter("attention"),
            "review": lambda: self._show_page("review"),
            "published": lambda: self._show_page("library"),
        }
        for index, (_label, key) in enumerate((
            ("En proceso", "active"), ("Necesitan atención", "failed"),
            ("Decisiones pendientes", "review"), ("En la biblioteca", "published"),
        )):
            card = tk.Button(
                metrics,
                textvariable=self.dashboard_card_vars[key],
                command=card_actions[key],
                bg=self.colors["raised"],
                fg=self.colors["text"],
                activebackground="#223038",
                activeforeground=self.colors["text"],
                highlightbackground=self.colors["border"],
                highlightcolor=self.colors["accent"],
                highlightthickness=1,
                relief="flat",
                borderwidth=0,
                cursor="hand2",
                font=("Segoe UI Semibold", 12),
                justify="left",
                anchor="w",
                padx=16,
                pady=12,
            )
            card.grid(row=0, column=index, sticky="ew", padx=6)

        system = tk.Frame(
            page,
            bg=self.colors["raised"],
            highlightbackground=self.colors["border"],
            highlightthickness=1,
        )
        system.grid(row=3, column=0, sticky="ew", padx=28, pady=(18, 0))
        system.columnconfigure(0, weight=1)
        self.system_message_var = tk.StringVar(value="Comprobando el servicio de procesamiento…")
        tk.Label(
            system,
            text="Estado del procesamiento",
            bg=self.colors["raised"],
            fg=self.colors["text"],
            font=("Segoe UI Semibold", 10),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 3))
        tk.Label(
            system,
            textvariable=self.system_message_var,
            bg=self.colors["raised"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
            anchor="w",
            justify="left",
            wraplength=1160,
        ).grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))

        attention = tk.Frame(page, bg=self.colors["surface"])
        attention.grid(row=4, column=0, sticky="nsew", padx=28, pady=22)
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
        ttk.Button(attention, text="Ver documentos que necesitan atención", style="Secondary.TButton",
                   command=lambda: self._open_document_filter("attention")).grid(
            row=2, column=0, sticky="e", pady=(12, 0)
        )

    def _refresh_dashboard(self) -> None:
        snapshot = self.snapshots.dashboard()
        self.dashboard_vars["active"].set(str(snapshot.active_captures))
        self.dashboard_vars["review"].set(str(snapshot.pending_review))
        self.dashboard_vars["failed"].set(str(snapshot.failed_captures))
        self.dashboard_vars["published"].set(str(snapshot.published_notes))
        self._sync_dashboard_cards()
        self.dashboard_vars["broker"].set(snapshot.broker_status)
        self.dashboard_vars["broker_message"].set(snapshot.broker_message)
        broker_online = snapshot.broker_status == "online"
        self.service_var.set("Orquestador activo")
        self.broker_var.set(f"Procesamiento: {'disponible' if broker_online else snapshot.broker_status}")
        self.system_message_var.set(
            "El procesamiento está disponible. Los documentos nuevos pueden continuar su flujo."
            if broker_online
            else f"El procesamiento no está confirmado: {snapshot.broker_message}. "
                 "Los documentos se conservan y continuarán cuando el servicio vuelva a estar disponible."
        )

    def _open_home_attention(self, _event: tk.Event) -> None:
        selection = self.home_attention.selection()
        if not selection:
            return
        self._work_filter = "attention"
        self._selected_work_id = str(selection[0])
        self._selected_work_ids = (self._selected_work_id,)
        self._show_page("work")
        self._refresh_work_list()

    def _open_document_filter(self, value: str) -> None:
        self._work_filter = value
        self._selected_work_id = None
        self._selected_work_ids = ()
        self._show_page("work")
        self._refresh_work_list(select_first=True)

    def _sync_dashboard_cards(self) -> None:
        labels = {
            "active": "En proceso",
            "failed": "Necesitan atención",
            "review": "Decisiones pendientes",
            "published": "En la biblioteca",
        }
        for key, label in labels.items():
            self.dashboard_card_vars[key].set(f"{self.dashboard_vars[key].get()}\n{label}")
