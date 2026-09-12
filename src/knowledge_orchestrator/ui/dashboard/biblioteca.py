"""Vista «Biblioteca»: el conocimiento publicado disponible en los vaults.

La biblioteca separa el resultado documental del trabajo técnico que lo creó.
Esa frontera también será la base natural de los futuros consumidores por API.

La vista previa lee la nota a través de `KnowledgeAccess.document`, que valida
que siga dentro de la bóveda y que su hash coincida: si alguien la editó en
Obsidian, se dice en vez de enseñar un contenido que ya no es el registrado.
La lectura va en un hilo; Tk solo pinta.
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from functools import partial
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import quote

from knowledge_orchestrator.ui.dashboard.estilo import FONT, FONT_SEMIBOLD, MONO
from knowledge_orchestrator.ui.dashboard.revision import RevisionMixin
from knowledge_orchestrator.ui.snapshots import LibraryItem

ALL_TOPICS = "Todos los temas"
PREVIEW_LIMIT = 20_000


class BibliotecaMixin(RevisionMixin):
    """Catálogo de notas publicadas con búsqueda, temas y vista previa."""

    def _build_library(self) -> None:
        c = self.colors
        page = self._new_page("library")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)
        self._page_heading(
            page,
            "Biblioteca",
            "El conocimiento publicado en tu bóveda de Obsidian, con su tema, revisión y origen.",
        )

        search_host = tk.Frame(page, bg=c["raised"], highlightbackground=c["border"], highlightthickness=1)
        search_host.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 10))
        self._icon(search_host, "search", size=11, color="faint", bg="raised").pack(side="left", padx=(12, 4))
        self.library_search_var = tk.StringVar()
        self.library_search_var.trace_add("write", lambda *_args: self._schedule_library_refresh())
        self.library_search_entry = ttk.Entry(search_host, textvariable=self.library_search_var,
                                              style="Search.TEntry")
        self.library_search_entry.pack(side="left", fill="x", expand=True)
        self._text(search_host, "Título, tema o ruta · Ctrl+F", size=8, color="faint",
                   bg="raised").pack(side="right", padx=12)
        self.library_search_entry.bind(
            "<FocusIn>", lambda _event: search_host.configure(highlightbackground=c["accent"]))
        self.library_search_entry.bind(
            "<FocusOut>", lambda _event: search_host.configure(highlightbackground=c["border"]))

        self.library_topics_host = tk.Frame(page, bg=c["surface"])
        self.library_topics_host.grid(row=2, column=0, sticky="w", padx=28, pady=(0, 12))
        self._library_topic = ALL_TOPICS
        self._library_topic_buttons: dict[str, tk.Button] = {}

        content = tk.PanedWindow(page, orient="horizontal", bg=c["border"], sashwidth=1, bd=0, relief="flat",
                                 showhandle=False)
        content.grid(row=3, column=0, sticky="nsew", padx=28, pady=(0, 20))
        list_frame = tk.Frame(content, bg=c["surface"])
        detail = tk.Frame(content, bg=c["surface"])
        content.add(list_frame, minsize=460, width=600, stretch="never")
        content.add(detail, minsize=420, stretch="always")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(3, weight=1)

        self.library_tree = ttk.Treeview(list_frame, columns=("tema", "revision", "publicada"),
                                         show="tree headings")
        self.library_tree.heading("#0", text="Documento")
        self.library_tree.heading("tema", text="Tema")
        self.library_tree.heading("revision", text="Rev.")
        self.library_tree.heading("publicada", text="Publicada")
        self.library_tree.column("#0", width=250, minwidth=180, stretch=True)
        self.library_tree.column("tema", width=110, minwidth=80, stretch=False)
        self.library_tree.column("revision", width=46, minwidth=42, anchor="center", stretch=False)
        self.library_tree.column("publicada", width=150, minwidth=140, stretch=False)
        self.library_tree.grid(row=0, column=0, sticky="nsew")
        self.library_tree.bind("<<TreeviewSelect>>", lambda _event: self._select_library_item())
        self.library_tree.bind("<Double-1>", lambda _event: self._open_in_obsidian())
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.library_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 12))
        self.library_tree.configure(yscrollcommand=scrollbar.set)
        self.library_summary_var = tk.StringVar(value="Aún no hay conocimiento publicado.")
        self._text(list_frame, textvariable=self.library_summary_var, size=9, color="faint").grid(
            row=1, column=0, sticky="ew", pady=10)

        self.library_title_var = tk.StringVar(value="Selecciona un documento")
        self.library_meta_var = tk.StringVar(value="Aquí verás su contexto documental.")
        self.library_path_var = tk.StringVar(value="")
        self._text(detail, textvariable=self.library_title_var, size=17, bold=True, wraplength=560).grid(
            row=0, column=0, sticky="ew", padx=(22, 8), pady=(2, 8))
        chips = tk.Frame(detail, bg=c["surface"])
        chips.grid(row=1, column=0, sticky="w", padx=22, pady=(0, 12))
        self.library_chips = [self._pill(chips) for _ in range(3)]
        self._text(detail, "Vista previa", bold=True).grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 6))
        self.library_preview = tk.Text(
            detail, height=10, wrap="word", bg=c["raised"], fg=c["muted"], relief="flat", padx=18, pady=12,
            font=(FONT, 10), highlightthickness=1, highlightbackground=c["border"], state="disabled",
            cursor="arrow", spacing1=2, spacing3=2,
        )
        self.library_preview.grid(row=3, column=0, sticky="nsew", padx=22)
        self.library_preview.tag_configure("h1", foreground=c["accent"], font=(FONT_SEMIBOLD, 13), spacing1=6)
        self.library_preview.tag_configure("h2", foreground=c["text"], font=(FONT_SEMIBOLD, 11), spacing1=6)
        self.library_preview.tag_configure("body", foreground=c["text"])
        self.library_preview.tag_configure("note", foreground=c["faint"], font=(FONT, 9))
        location = tk.Frame(detail, bg=c["surface"])
        location.grid(row=4, column=0, sticky="ew", padx=22, pady=(10, 0))
        self._text(location, "Ruta en la bóveda:", size=9, color="faint").pack(side="left")
        tk.Label(location, textvariable=self.library_path_var, bg=c["surface"], fg=c["muted"], font=(MONO, 9),
                 anchor="w").pack(side="left", padx=(6, 0))
        buttons = tk.Frame(detail, bg=c["surface"])
        buttons.grid(row=5, column=0, sticky="ew", padx=22, pady=(14, 4))
        self.library_obsidian_button = ttk.Button(buttons, text="Abrir en Obsidian", style="Accent.TButton",
                                                  command=self._open_in_obsidian)
        self.library_obsidian_button.pack(side="left", padx=(0, 8))
        self.library_open_button = ttk.Button(buttons, text="Abrir carpeta", command=self._open_library_location)
        self.library_open_button.pack(side="left", padx=(0, 8))
        self.library_source_button = ttk.Button(buttons, text="Ver documento de origen",
                                                command=self._open_library_source)
        self.library_source_button.pack(side="left")
        for button in (self.library_obsidian_button, self.library_open_button, self.library_source_button):
            button.state(["disabled"])

        self._library_preview_queue: queue.SimpleQueue[tuple[int, str | None, str | None]] = queue.SimpleQueue()
        self._library_preview_id: int | None = None
        self._library_preview_pending = 0

    # ------------------------------------------------------------ datos

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

    def _sync_topic_chips(self, topics: list[str]) -> None:
        wanted = [ALL_TOPICS, *topics]
        if list(self._library_topic_buttons) != wanted:
            for button in self._library_topic_buttons.values():
                button.destroy()
            self._library_topic_buttons = {}
            c = self.colors
            for topic in wanted:
                button = tk.Button(
                    self.library_topics_host, text=topic, command=partial(self._set_library_topic, topic),
                    bg=c["surface"], fg=c["muted"], activebackground=c["raised"], activeforeground=c["text"],
                    relief="flat", bd=0, highlightthickness=1, highlightbackground=c["border"], padx=12, pady=5,
                    font=(FONT_SEMIBOLD, 9), cursor="hand2",
                )
                button.pack(side="left", padx=(0, 6))
                self._library_topic_buttons[topic] = button
        if self._library_topic not in self._library_topic_buttons:
            self._library_topic = ALL_TOPICS
        for topic, button in self._library_topic_buttons.items():
            selected = topic == self._library_topic
            button.configure(bg=self.colors["accent_dark"] if selected else self.colors["surface"],
                             fg=self.colors["accent"] if selected else self.colors["muted"],
                             highlightbackground=self.colors["accent"] if selected else self.colors["border"])

    def _set_library_topic(self, topic: str) -> None:
        self._library_topic = topic
        self._refresh_library_list()

    def _refresh_library_list(self) -> None:
        if not hasattr(self, "library_tree"):
            return
        all_items = list(self._library_items.values())
        self._sync_topic_chips(sorted({item.topic for item in all_items}, key=str.casefold))
        items = [item for item in all_items if self._library_topic in {ALL_TOPICS, item.topic}]
        rows = [(str(item.note_id), (item.topic, item.revision, item.published_label)) for item in items]
        self._replace_tree(self.library_tree, rows, texts={str(item.note_id): item.title for item in items})
        if items:
            count = len(items)
            self.library_summary_var.set(f"{count} nota{'s' if count != 1 else ''} publicada{'s' if count != 1 else ''}"
                                         " · Doble clic para abrir en Obsidian")
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

    # ------------------------------------------------------------ pintado

    def _relative_vault_path(self, value: str) -> str:
        try:
            return str(Path(value).relative_to(self.runtime.paths.obsidian_vault))
        except ValueError:
            return value

    def _render_library_item(self, item: LibraryItem) -> None:
        self.library_title_var.set(item.title)
        self.library_meta_var.set(
            f"{item.topic} · Revisión {item.revision} · Publicada {item.published_label}"
        )
        for pill, (text, tone) in zip(self.library_chips, (
            (f"Tema: {item.topic}", "accent"), (f"Revisión {item.revision}", "neutral"),
            (f"Publicada {item.published_label}", "neutral"),
        ), strict=True):
            self._set_pill(pill, text, tone="neutral" if tone == "neutral" else tone)
            pill.configure(text=text)
            pill.pack(side="left", padx=(0, 6))
        self.library_path_var.set(
            self._relative_vault_path(item.vault_path) if item.vault_path
            else "La ubicación todavía no está disponible."
        )
        available = ["!disabled"] if item.vault_path else ["disabled"]
        self.library_open_button.state(available)
        self.library_obsidian_button.state(available)
        self.library_source_button.state(["!disabled"])
        self._load_library_preview(item)

    def _render_empty_library(self) -> None:
        has_query = bool(self.library_search_var.get().strip())
        self.library_title_var.set("Sin resultados" if has_query else "Selecciona una nota")
        self.library_meta_var.set(
            "Prueba con otra búsqueda."
            if has_query
            else "Los documentos publicados aparecerán aquí con su contexto documental."
        )
        for pill in self.library_chips:
            pill.pack_forget()
        self.library_path_var.set("—")
        for button in (self.library_obsidian_button, self.library_open_button, self.library_source_button):
            button.state(["disabled"])
        self._library_preview_id = None
        self._write_preview("Elige una nota de la lista para leer su contenido sin salir de la aplicación.",
                            markdown=False)

    # ---------------------------------------------------------- vista previa

    def _load_library_preview(self, item: LibraryItem) -> None:
        if self._library_preview_id == item.note_id:
            return
        self._library_preview_id = item.note_id
        self._write_preview("Cargando vista previa…", markdown=False)
        access, results, note_id = self.runtime.knowledge_access, self._library_preview_queue, item.note_id

        def read() -> None:
            try:
                results.put((note_id, access.document(note_id)["content"], None))
            except Exception as error:  # noqa: BLE001 - el motivo se enseña tal cual al usuario
                results.put((note_id, None, str(error) or "No se pudo leer la nota."))

        self._library_preview_pending += 1
        threading.Thread(target=read, name="library-preview", daemon=True).start()
        self.after(50, self._poll_library_preview)

    def _poll_library_preview(self) -> None:
        try:
            note_id, content, error = self._library_preview_queue.get_nowait()
        except queue.Empty:
            if self._library_preview_pending:
                self.after(50, self._poll_library_preview)
            return
        self._library_preview_pending -= 1
        if note_id == self._library_preview_id:
            if content is None:
                self._write_preview(f"No se puede mostrar la vista previa: {error}", markdown=False)
            else:
                self._write_preview(content, markdown=True)
        if self._library_preview_pending:
            self.after(50, self._poll_library_preview)

    def _write_preview(self, content: str, *, markdown: bool) -> None:
        text = self.library_preview
        text.configure(state="normal")
        text.delete("1.0", "end")
        if not markdown:
            text.insert("end", content, "note")
        else:
            body = content[:PREVIEW_LIMIT]
            lines = body.splitlines()
            if lines and lines[0].strip() == "---" and "---" in (line.strip() for line in lines[1:]):
                closing = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
                lines = lines[closing + 1:]
            for line in lines:
                stripped = line.lstrip()
                if stripped.startswith("# "):
                    text.insert("end", stripped[2:] + "\n", "h1")
                elif stripped.startswith("#"):
                    text.insert("end", stripped.lstrip("#").strip() + "\n", "h2")
                else:
                    text.insert("end", line + "\n", "body")
            if len(content) > PREVIEW_LIMIT:
                text.insert("end", "\nVista parcial. Abre la nota en Obsidian para leerla completa.", "note")
        text.configure(state="disabled")

    # --------------------------------------------------------------- acciones

    def _selected_library_item(self) -> LibraryItem | None:
        if self._selected_library_id is None:
            return None
        return self._library_items.get(str(self._selected_library_id))

    def _open_library_location(self) -> None:
        item = self._selected_library_item()
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

    def _open_in_obsidian(self) -> None:
        item = self._selected_library_item()
        if item is None or not item.vault_path:
            return
        path = Path(item.vault_path)
        if not path.exists():
            messagebox.showinfo("Nota no disponible", "La nota ya no está en la ubicación registrada.", parent=self)
            return
        try:
            os.startfile("obsidian://open?path=" + quote(str(path), safe=""))
        except OSError as error:
            messagebox.showerror(
                "No se pudo abrir Obsidian",
                f"{error}\n\nComprueba que Obsidian está instalado y que la bóveda está abierta en él. "
                "También puedes usar «Abrir carpeta».",
                parent=self,
            )

    def _open_library_source(self) -> None:
        item = self._selected_library_item()
        if item is None:
            return
        self.search_var.set("")
        self._work_items = {work.capture_id: work for work in self.snapshots.work_items()}
        self._work_filter = "all"
        self._selected_work_id = item.capture_id
        self._selected_work_ids = (item.capture_id,)
        self._show_page("work")
        self._refresh_work_list()
