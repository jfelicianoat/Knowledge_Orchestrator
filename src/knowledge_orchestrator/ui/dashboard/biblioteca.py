"""Vista «Biblioteca»: el conocimiento publicado disponible en los vaults.

La biblioteca separa el resultado documental del trabajo técnico que lo creó.
Esa frontera también será la base natural de los futuros consumidores por API.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from knowledge_orchestrator.ui.dashboard.revision import RevisionMixin
from knowledge_orchestrator.ui.snapshots import LibraryItem


class BibliotecaMixin(RevisionMixin):
    """Catálogo de notas publicadas con búsqueda y contexto documental."""

    def _build_library(self) -> None:
        page = self._new_page("library")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)
        self._page_heading(
            page,
            "Biblioteca",
            "Consulta el conocimiento publicado, con su tema, revisión y ubicación en Obsidian.",
        )

        toolbar = tk.Frame(page, bg=self.colors["surface"])
        toolbar.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 14))
        toolbar.columnconfigure(1, weight=1)
        tk.Label(
            toolbar,
            text="Buscar en la biblioteca",
            bg=self.colors["surface"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.library_search_var = tk.StringVar()
        self.library_search_var.trace_add("write", lambda *_args: self._schedule_library_refresh())
        self.library_search_entry = ttk.Entry(
            toolbar,
            textvariable=self.library_search_var,
            style="Dark.TEntry",
        )
        self.library_search_entry.grid(row=0, column=1, sticky="ew")

        content = tk.PanedWindow(
            page,
            orient="horizontal",
            bg=self.colors["border"],
            sashwidth=2,
            bd=0,
            relief="flat",
            showhandle=False,
        )
        content.grid(row=3, column=0, sticky="nsew", padx=24, pady=(0, 24))
        list_frame = tk.Frame(content, bg=self.colors["surface"])
        detail = tk.Frame(content, bg=self.colors["surface"])
        content.add(list_frame, minsize=620, stretch="always")
        content.add(detail, minsize=360, stretch="always")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(4, weight=1)

        columns = ("tema", "revision", "publicada")
        self.library_tree = ttk.Treeview(
            list_frame,
            columns=columns,
            show="tree headings",
            style="Dark.Treeview",
        )
        self.library_tree.heading("#0", text="Documento")
        self.library_tree.heading("tema", text="Tema")
        self.library_tree.heading("revision", text="Revisión")
        self.library_tree.heading("publicada", text="Publicada")
        self.library_tree.column("#0", width=330, minwidth=220)
        self.library_tree.column("tema", width=170, minwidth=120)
        self.library_tree.column("revision", width=80, minwidth=70, anchor="center")
        self.library_tree.column("publicada", width=150, minwidth=125)
        self.library_tree.grid(row=0, column=0, sticky="nsew")
        self.library_tree.bind("<<TreeviewSelect>>", lambda _event: self._select_library_item())
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.library_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.library_tree.configure(yscrollcommand=scrollbar.set)

        self.library_summary_var = tk.StringVar(value="Aún no hay conocimiento publicado.")
        tk.Label(
            list_frame,
            textvariable=self.library_summary_var,
            bg=self.colors["surface"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
            anchor="w",
            pady=12,
        ).grid(row=1, column=0, sticky="ew")

        self.library_title_var = tk.StringVar(value="Selecciona un documento")
        self.library_meta_var = tk.StringVar(value="Aquí verás su contexto documental.")
        self.library_path_var = tk.StringVar(value="")
        tk.Label(
            detail,
            textvariable=self.library_title_var,
            bg=self.colors["surface"],
            fg=self.colors["text"],
            font=("Segoe UI Semibold", 17),
            anchor="w",
            wraplength=520,
            justify="left",
        ).grid(row=0, column=0, sticky="ew", padx=26, pady=(20, 8))
        tk.Label(
            detail,
            textvariable=self.library_meta_var,
            bg=self.colors["surface"],
            fg=self.colors["muted"],
            font=("Segoe UI", 10),
            anchor="w",
            wraplength=520,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", padx=26)
        tk.Label(
            detail,
            text="Ubicación en el vault",
            bg=self.colors["surface"],
            fg=self.colors["text"],
            font=("Segoe UI Semibold", 10),
            anchor="w",
        ).grid(row=2, column=0, sticky="ew", padx=26, pady=(24, 7))
        tk.Label(
            detail,
            textvariable=self.library_path_var,
            bg=self.colors["raised"],
            fg=self.colors["muted"],
            font=("Consolas", 9),
            anchor="nw",
            justify="left",
            wraplength=520,
            padx=14,
            pady=12,
        ).grid(row=3, column=0, sticky="ew", padx=26)
        self.library_open_button = ttk.Button(
            detail,
            text="Abrir carpeta del vault",
            style="Accent.TButton",
            command=self._open_library_location,
        )
        self.library_open_button.grid(row=5, column=0, sticky="ew", padx=26, pady=(18, 20))
        self.library_open_button.state(["disabled"])

    def _refresh_library(self) -> None:
        items = self.snapshots.library_items(self.library_search_var.get())
        self._library_items = {str(item.note_id): item for item in items}
        self._refresh_library_list()

    def _schedule_library_refresh(self) -> None:
        if self._library_search_job is not None:
            self.after_cancel(self._library_search_job)
        self._library_search_job = self.after(250, self._run_scheduled_library_refresh)

    def _run_scheduled_library_refresh(self) -> None:
        self._library_search_job = None
        self._refresh_library()

    def _refresh_library_list(self) -> None:
        if not hasattr(self, "library_tree"):
            return
        items = list(self._library_items.values())
        rows = [
            (
                str(item.note_id),
                (item.topic, f"r{item.revision}", item.published_label),
            )
            for item in items
        ]
        self._replace_tree(
            self.library_tree,
            rows,
            texts={str(item.note_id): item.title for item in items},
        )
        if items:
            self.library_summary_var.set(f"{len(items)} documentos publicados encontrados")
        elif self.library_search_var.get().strip():
            self.library_summary_var.set("No hay documentos que coincidan con la búsqueda.")
        else:
            self.library_summary_var.set(
                "Aún no hay conocimiento publicado. Los documentos completados aparecerán aquí."
            )
        selected_id = str(self._selected_library_id) if self._selected_library_id is not None else ""
        if selected_id in {row_id for row_id, _values in rows}:
            self.library_tree.selection_set(selected_id)
            self._render_library_item(self._library_items[selected_id])
        else:
            self._selected_library_id = None
            self._render_empty_library()

    def _select_library_item(self) -> None:
        selection = self.library_tree.selection()
        if not selection:
            self._selected_library_id = None
            self._render_empty_library()
            return
        item = self._library_items.get(str(selection[0]))
        if item is None:
            return
        self._selected_library_id = item.note_id
        self._render_library_item(item)

    def _render_library_item(self, item: LibraryItem) -> None:
        self.library_title_var.set(item.title)
        self.library_meta_var.set(
            f"{item.topic} · Revisión {item.revision} · Publicada {item.published_label}"
        )
        self.library_path_var.set(item.vault_path or "La ubicación todavía no está disponible.")
        self.library_open_button.state(["!disabled"] if item.vault_path else ["disabled"])

    def _render_empty_library(self) -> None:
        has_query = bool(self.library_search_var.get().strip())
        self.library_title_var.set("Sin resultados" if has_query else "Biblioteca vacía")
        self.library_meta_var.set(
            "Prueba con otra búsqueda."
            if has_query
            else "Los documentos publicados aparecerán aquí con su contexto documental."
        )
        self.library_path_var.set("—")
        self.library_open_button.state(["disabled"])

    def _open_library_location(self) -> None:
        if self._selected_library_id is None:
            return
        item = self._library_items.get(str(self._selected_library_id))
        if item is None or not item.vault_path:
            return
        path = Path(item.vault_path)
        target = path if path.is_dir() else path.parent
        if not target.exists():
            messagebox.showinfo(
                "Ubicación no disponible",
                "La nota ya no se encuentra en la ubicación registrada.",
                parent=self,
            )
            return
        self._open_path(target)
