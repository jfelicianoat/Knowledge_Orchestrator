"""Vista «Inicio»: el estado del sistema de un vistazo.

STORY: el usuario ve qué documentos avanzan y detecta qué requiere atención.
Las tarjetas son un resumen, no el producto: cada una lleva a la lista donde se
actúa, y la lista de atención abre el documento concreto con doble clic.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from tkinter import ttk

from knowledge_orchestrator.ui.dashboard.base import DashboardBase
from knowledge_orchestrator.ui.dashboard.estilo import FONT, FONT_SEMIBOLD, TONES

KPI_CARDS = (
    ("active", "En proceso", "sync", "accent"),
    ("failed", "Necesitan atención", "warning", "error"),
    ("review", "Decisiones pendientes", "question", "warning"),
    ("published", "En la biblioteca", "library", "success"),
)


def event_tone(event_type: str) -> str:
    """Tono de un evento para cronologías: el texto siempre acompaña al color."""

    kind = event_type.upper()
    if any(word in kind for word in ("ERROR", "FAILED", "CRASH", "OFFLINE", "REJECT", "QUARANTIN")):
        return "error"
    if any(word in kind for word in ("WARNING", "CONFLICT", "IGNORED", "CANCEL")):
        return "warning"
    if any(word in kind for word in ("COMPLETED", "PUBLISHED", "APPLIED", "SUCCESS", "ONLINE")):
        return "success"
    return "accent"


class InicioMixin(DashboardBase):
    """Saludo, indicadores, recorrido del conocimiento, atención y actividad."""

    def _build_home(self) -> None:
        c = self.colors
        page = self._new_page("home")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(4, weight=1)

        header = tk.Frame(page, bg=c["surface"])
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 14))
        self.home_greeting_var = tk.StringVar(value=self._greeting())
        self.home_subtitle_var = tk.StringVar(value="Comprobando el estado de tus documentos…")
        self._text(header, textvariable=self.home_greeting_var, size=20, bold=True).pack(fill="x")
        self._text(header, textvariable=self.home_subtitle_var, color="muted").pack(fill="x", pady=(2, 0))

        self.dashboard_vars = {
            "active": tk.StringVar(value="0"), "review": tk.StringVar(value="0"),
            "failed": tk.StringVar(value="0"), "published": tk.StringVar(value="0"),
            "broker": tk.StringVar(value="sin datos"), "broker_message": tk.StringVar(value=""),
        }
        self.dashboard_card_vars = {key: tk.StringVar(value="0") for key, *_rest in KPI_CARDS}
        actions: dict[str, Callable[[], None]] = {
            "active": lambda: self._open_document_filter("active"),
            "failed": lambda: self._open_document_filter("attention"),
            "review": lambda: self._show_page("review"),
            "published": lambda: self._show_page("library"),
        }
        metrics = tk.Frame(page, bg=c["surface"])
        metrics.grid(row=1, column=0, sticky="ew", padx=22)
        metrics.columnconfigure((0, 1, 2, 3), weight=1, uniform="kpi")
        for index, (key, label, icon, tone) in enumerate(KPI_CARDS):
            self._kpi_card(metrics, index, key, label, icon, tone, actions[key])

        self.system_message_var = tk.StringVar(value="Comprobando el servicio de procesamiento…")
        warning_bg, warning_fg = TONES["warning"]
        self.system_banner = self._card(page, bg=warning_bg, border="#5c4516")
        self.system_banner.grid(row=2, column=0, sticky="ew", padx=28, pady=(14, 0))
        self.system_banner.columnconfigure(1, weight=1)
        self._icon(self.system_banner, "warning", size=16, color=warning_fg, bg=warning_bg).grid(
            row=0, column=0, rowspan=2, sticky="n", padx=(16, 12), pady=14)
        self._text(self.system_banner, "El procesamiento no está confirmado", bold=True, color=warning_fg,
                   bg=warning_bg).grid(row=0, column=1, sticky="ew", pady=(12, 2))
        self._text(self.system_banner, textvariable=self.system_message_var, size=9, color="text", bg=warning_bg,
                   wraplength=980).grid(row=1, column=1, sticky="ew", pady=(0, 12), padx=(0, 16))
        self.system_banner.grid_remove()

        pipeline = self._card(page)
        pipeline.grid(row=3, column=0, sticky="ew", padx=28, pady=(14, 0))
        heading = tk.Frame(pipeline, bg=c["raised"])
        heading.pack(fill="x", padx=18, pady=(14, 4))
        self._text(heading, "Recorrido del conocimiento", bold=True, bg="raised").pack(side="left")
        self._text(heading, "Pulsa una etapa para ver sus elementos", size=9, color="faint",
                   bg="raised").pack(side="right")
        self.lifecycle_host = tk.Frame(pipeline, bg=c["raised"])
        self.lifecycle_host.pack(fill="x", padx=18, pady=(4, 2))

        bottom = tk.Frame(page, bg=c["surface"])
        bottom.grid(row=4, column=0, sticky="nsew", padx=28, pady=(14, 20))
        bottom.columnconfigure(0, weight=3, uniform="home")
        bottom.columnconfigure(1, weight=2, uniform="home")
        bottom.rowconfigure(0, weight=1)

        attention = self._card(bottom)
        attention.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        attention.columnconfigure(0, weight=1)
        attention.rowconfigure(1, weight=1)
        top = tk.Frame(attention, bg=c["raised"])
        top.grid(row=0, column=0, sticky="ew", padx=(18, 10), pady=(12, 6))
        self._text(top, "Necesita tu atención", size=12, bold=True, bg="raised").pack(side="left")
        ttk.Button(top, text="Ver todos", style="Ghost.TButton",
                   command=lambda: self._open_document_filter("attention")).pack(side="right")
        ttk.Style(self).configure("Ghost.TButton", background=c["raised"], bordercolor=c["raised"],
                                  lightcolor=c["raised"], darkcolor=c["raised"])
        self.home_attention = ttk.Treeview(
            attention, columns=("estado", "actualizado"), show="tree", style="Card.Treeview", height=5,
            selectmode="browse",
        )
        self.home_attention.column("#0", width=340, minwidth=200, stretch=True)
        self.home_attention.column("estado", width=160, minwidth=120, stretch=False)
        self.home_attention.column("actualizado", width=100, minwidth=80, stretch=False)
        self.home_attention.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 12))
        self.home_attention.tag_configure("error", foreground="#ff9aa0")
        self.home_attention.tag_configure("warning", foreground="#f5c56b")
        self.home_attention.bind("<Double-1>", self._open_home_attention)
        self.home_attention.bind("<Return>", self._open_home_attention)
        self.home_attention_empty = self._text(
            attention, "Todo en orden: ningún documento necesita tu atención.", color="muted", bg="raised",
        )
        self.home_attention_empty.grid(row=1, column=0, sticky="nw", padx=18, pady=(4, 12))
        self.home_attention_empty.grid_remove()

        activity = self._card(bottom)
        activity.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        activity.columnconfigure(0, weight=1)
        activity.rowconfigure(1, weight=1)
        self._text(activity, "Actividad reciente", size=12, bold=True, bg="raised").grid(
            row=0, column=0, sticky="ew", padx=18, pady=(14, 6))
        self.home_activity = tk.Text(
            activity, bg=c["raised"], fg=c["text"], height=8, wrap="word", relief="flat", padx=18, pady=4,
            cursor="arrow", font=(FONT, 10), state="disabled", highlightthickness=0, spacing1=5, spacing3=5,
        )
        # Las líneas largas continúan alineadas tras la hora, no bajo ella.
        self.home_activity.configure(tabs=("48p",))
        self.home_activity.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        for tone, (_background, foreground) in TONES.items():
            self.home_activity.tag_configure(f"dot_{tone}", foreground=foreground)
            self.home_activity.tag_configure(f"label_{tone}", foreground=foreground, font=(FONT_SEMIBOLD, 10))
        self.home_activity.tag_configure("subject", foreground=c["text"])
        self.home_activity.tag_configure("time", foreground=c["faint"], font=(FONT, 9))
        self.home_activity.tag_configure("empty", foreground=c["muted"])
        self._home_activity_signature: tuple | None = None

    def _kpi_card(self, parent: tk.Frame, index: int, key: str, label: str, icon: str, tone: str,
                  action: Callable[[], None]) -> None:
        c = self.colors
        color = TONES[tone][1]
        card = self._card(parent)
        card.configure(cursor="hand2", takefocus=1, highlightcolor=c["accent"])
        card.grid(row=0, column=index, sticky="ew", padx=6)
        card.columnconfigure(0, weight=1)
        number = tk.Label(card, textvariable=self.dashboard_card_vars[key], bg=c["raised"], fg=color,
                          font=(FONT_SEMIBOLD, 26), anchor="w", cursor="hand2")
        number.grid(row=0, column=0, sticky="w", padx=(18, 8), pady=(12, 0))
        glyph = self._icon(card, icon, size=22, color=color, bg="raised", cursor="hand2")
        glyph.grid(row=0, column=1, rowspan=2, sticky="e", padx=18)
        caption = self._text(card, label, color="muted", bg="raised", cursor="hand2")
        caption.grid(row=1, column=0, sticky="w", padx=18, pady=(0, 14))
        widgets = (card, number, glyph, caption)

        def hover(inside: bool) -> None:
            for widget in widgets:
                widget.configure(bg=c["hover"] if inside else c["raised"])

        for widget in widgets:
            widget.bind("<Button-1>", lambda _event: action())
            widget.bind("<Enter>", lambda _event: hover(True))
            widget.bind("<Leave>", lambda _event: hover(False))
        card.bind("<Return>", lambda _event: action())

    @staticmethod
    def _greeting() -> str:
        hour = datetime.now().hour
        if 6 <= hour < 13:
            return "Buenos días"
        if 13 <= hour < 21:
            return "Buenas tardes"
        return "Buenas noches"

    @staticmethod
    def _event_tone(event_type: str) -> str:
        return event_tone(event_type)

    def _refresh_dashboard(self) -> None:
        snapshot = self.snapshots.dashboard()
        self.dashboard_vars["active"].set(str(snapshot.active_captures))
        self.dashboard_vars["review"].set(str(snapshot.pending_review))
        self.dashboard_vars["failed"].set(str(snapshot.failed_captures))
        self.dashboard_vars["published"].set(str(snapshot.published_notes))
        self._sync_dashboard_cards()
        # Lo que dice el worker en vivo manda sobre lo guardado: sus eventos de
        # salud no se persisten y la base se quedaba en «sin datos».
        broker_status, broker_message = self._live_broker or (snapshot.broker_status, snapshot.broker_message)
        self.dashboard_vars["broker"].set(broker_status)
        self.dashboard_vars["broker_message"].set(broker_message)
        broker_online = broker_status == "online"
        unknown = broker_status == "sin datos"
        self.service_var.set("Orquestador activo")
        self.service_dot.configure(fg=self.colors["success"])
        self.broker_var.set("Broker disponible" if broker_online else "Broker sin comprobar" if unknown
                            else "Broker con incidencia")
        self.broker_dot.configure(fg=self.colors["success"] if broker_online else self.colors["faint"] if unknown
                                  else self.colors["warning"])
        self.system_message_var.set(
            "El procesamiento está disponible. Los documentos nuevos pueden continuar su flujo."
            if broker_online
            else f"No hay respuesta del Broker en {self.runtime.broker_worker.settings.base_url}. "
                 "Los documentos se conservan y continuarán cuando vuelva a estar disponible. "
                 f"Puedes revisar la dirección y el token en Ajustes. Detalle técnico: {broker_message}"
        )
        if broker_online or unknown:
            self.system_banner.grid_remove()
        else:
            self.system_banner.grid()
        self.home_greeting_var.set(self._greeting())
        self._refresh_home_activity()

    def _refresh_home_activity(self) -> None:
        items = self.snapshots.recent_activity(limit=8)
        signature = tuple((item.event_type, item.created_at, item.title) for item in items)
        if signature == self._home_activity_signature:
            return
        self._home_activity_signature = signature
        text = self.home_activity
        text.configure(state="normal")
        text.delete("1.0", "end")
        if not items:
            text.insert("end", "Todavía no hay actividad. Importa un documento para empezar.", "empty")
        for item in items:
            tone = self._event_tone(item.event_type)
            subject = item.title or (item.message[:60] + ("…" if len(item.message) > 60 else ""))
            # La hora va delante: al final se partía a la línea siguiente.
            text.insert("end", f"{item.created_label[:5]}  ", "time")
            text.insert("end", "●  ", f"dot_{tone}")
            text.insert("end", self._event_label(item.event_type), f"label_{tone}")
            if subject:
                text.insert("end", f" · {subject}", "subject")
            text.insert("end", "\n")
        text.configure(state="disabled")

    def _toggle_home_empty(self, empty: bool) -> None:
        if empty:
            self.home_attention.grid_remove()
            self.home_attention_empty.grid()
        else:
            self.home_attention_empty.grid_remove()
            self.home_attention.grid()

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
        values = {key: self.dashboard_vars[key].get() for key, *_rest in KPI_CARDS}
        for key, value in values.items():
            self.dashboard_card_vars[key].set(value)

        def number(key: str) -> int:
            try:
                return int(values[key])
            except ValueError:
                return 0

        failed, review = number("failed"), number("review")
        parts = []
        if failed:
            parts.append(f"{failed} documento{'s' if failed != 1 else ''} "
                         f"necesita{'n' if failed != 1 else ''} tu atención")
        if review:
            parts.append(f"{review} decisi{'ones' if review != 1 else 'ón'} pendiente{'s' if review != 1 else ''}")
        self.home_subtitle_var.set(" · ".join(parts) if parts
                                   else "Todo en orden. Los documentos nuevos se procesarán automáticamente.")
