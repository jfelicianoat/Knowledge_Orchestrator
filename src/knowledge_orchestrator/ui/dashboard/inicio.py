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
            card = tk.Frame(
            metrics,
            bg=self.colors["raised"],
            highlightbackground=self.colors["border"],
            highlightthickness=1,
        )
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

    def _open_home_attention(self, _event: tk.Event) -> None:
        selection = self.home_attention.selection()
        if not selection:
            return
        self._work_filter = "attention"
        self._selected_work_id = str(selection[0])
        self._show_page("work")
        self._refresh_work_list()
