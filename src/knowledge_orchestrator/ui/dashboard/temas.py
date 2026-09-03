"""Vista «Temas»: cómo se clasifica y publica el conocimiento."""
from __future__ import annotations

from tkinter import ttk

from knowledge_orchestrator.ui.dashboard.revision import RevisionMixin


class TemasMixin(RevisionMixin):
    """Listado de temas y su perfil asignado."""

    def _build_topics(self) -> None:
        page = self._new_page("topics")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        self._page_heading(page, "Temas", "Consulta cómo se clasifica y publica el conocimiento.")
        columns = ("pos", "nombre", "carpeta", "perfil", "activo")
        self.topics_tree = ttk.Treeview(page, columns=columns, show="headings", style="Dark.Treeview")
        cabeceras_temas = {
            "pos": "#", "nombre": "Tema", "carpeta": "Carpeta", "perfil": "Perfil", "activo": "Activo",
        }
        for column, text in cabeceras_temas.items():
            self.topics_tree.heading(column, text=text)
            self.topics_tree.column(column, width=90 if column in {"pos", "activo"} else 260)
        self.topics_tree.grid(row=2, column=0, sticky="nsew", padx=24, pady=(0, 24))

    def _refresh_topics(self) -> None:
        self._replace_tree(
            self.topics_tree,
            [(str(item.topic_id), (item.position, item.name, item.folder, item.default_profile,
              "sí" if item.enabled else "no")) for item in self.snapshots.topics()],
        )
