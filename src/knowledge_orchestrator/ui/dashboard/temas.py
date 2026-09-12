"""Vista «Organización»: cómo se clasifica y publica el conocimiento."""
from __future__ import annotations

from tkinter import ttk

from knowledge_orchestrator.ui.dashboard.biblioteca import BibliotecaMixin

#: `_inbox` se guarda con la posición máxima de SQLite para quedar el último;
#: ese número no significa nada para el usuario.
RESERVED_POSITION = 2_000_000_000


def topic_order_label(position: int) -> str:
    return "Último (reserva)" if position >= RESERVED_POSITION else str(position)


class TemasMixin(BibliotecaMixin):
    """Listado de temas y su perfil asignado."""

    def _build_topics(self) -> None:
        c = self.colors
        page = self._new_page("topics")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        self._page_heading(
            page,
            "Organización",
            "Cómo se clasifica el conocimiento en carpetas y qué perfil de procesamiento usa cada tema.",
        )
        info = self._card(page)
        info.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 14))
        info.columnconfigure(1, weight=1)
        self._icon(info, "info", size=15, color="accent", bg="raised").grid(row=0, column=0, sticky="n",
                                                                           padx=(16, 12), pady=14)
        self._text(
            info,
            "Cada documento nuevo se asigna al primer tema activo cuyas palabras clave coinciden; si ninguno "
            "coincide, va a «_inbox». El perfil del tema decide modelo, privacidad y presupuesto.",
            size=9, color="muted", bg="raised", wraplength=900,
        ).grid(row=0, column=1, sticky="ew", pady=14)
        ttk.Button(info, text="Editar perfiles en Ajustes", command=lambda: self._show_page("config")).grid(
            row=0, column=2, padx=16, pady=10)

        columns = ("nombre", "carpeta", "perfil", "activo", "pos")
        self.topics_tree = ttk.Treeview(page, columns=columns, show="headings")
        for column, text, width in (("nombre", "Tema", 220), ("carpeta", "Carpeta en la bóveda", 260),
                                    ("perfil", "Perfil de procesamiento", 240), ("activo", "Estado", 110),
                                    ("pos", "Orden", 130)):
            self.topics_tree.heading(column, text=text)
            self.topics_tree.column(column, width=width, minwidth=80)
        self.topics_tree.tag_configure("inactive", foreground=c["faint"])
        self.topics_tree.grid(row=2, column=0, sticky="nsew", padx=28, pady=(0, 24))

    def _refresh_topics(self) -> None:
        topics = self.snapshots.topics()
        self._replace_tree(
            self.topics_tree,
            [(str(item.topic_id), (item.name, item.folder, item.default_profile or "—",
              "✓  Activo" if item.enabled else "○  Inactivo", topic_order_label(item.position)))
             for item in topics],
            tags={str(item.topic_id): (() if item.enabled else ("inactive",)) for item in topics},
        )
