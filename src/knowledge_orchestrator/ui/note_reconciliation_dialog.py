"""THESIS: una nota editada o movida en Obsidian se resuelve aquí, sin consola ni SQL.
OWN-WORLD: misma superficie grafito/cian; lista de notas afectadas y contenido actual al lado.
STORY: ver qué cambió, y elegir: adoptar la edición, localizar el fichero movido o retirar la nota.
FIRST VIEWPORT: notas afectadas a la izquierda, su texto actual a la derecha, decisiones al pie.
FORM: diálogo modal; adoptar va ligado al hash del texto mostrado (auditoría H14).
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from knowledge_orchestrator.ui.automation_plan import text_panel, write_text

STATE_TEXT = {
    "CONFLICT": "Editada fuera de la aplicación",
    "MISSING": "No está en su sitio (movida o borrada)",
}


class NoteReconciliationDialog(tk.Toplevel):
    def __init__(self, parent: Any, service: Any, *, on_change: Any) -> None:
        super().__init__(parent)
        self.service, self.on_change = service, on_change
        self._shown_hash: str | None = None
        self.title("Notas cambiadas fuera de la aplicación")
        self.geometry("1040x620")
        self.minsize(760, 460)
        self.transient(parent)
        self.configure(bg=parent.colors["surface"])
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(self, wraplength=1000, justify="left", text=(
            "Estas notas ya no coinciden con lo que publicó la aplicación. Mientras no se resuelvan, sus "
            "afirmaciones no se consideran vigentes y no se proponen cambios sobre ellas. Nada de lo que "
            "hagas aquí sobrescribe tu edición."
        )).grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(14, 8))
        self.tree = ttk.Treeview(self, columns=("estado",), show="tree headings", selectmode="browse",
                                 style="Dark.Treeview")
        self.tree.heading("#0", text="Nota")
        self.tree.heading("estado", text="Situación")
        self.tree.column("#0", width=260)
        self.tree.column("estado", width=190, stretch=False)
        self.tree.grid(row=1, column=0, sticky="nsew", padx=(16, 8))
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._select())
        frame, self.body = text_panel(self, parent.colors)
        frame.grid(row=1, column=1, sticky="nsew", padx=(8, 16))
        footer = ttk.Frame(self)
        footer.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=12)
        self.adopt_button = ttk.Button(footer, text="Adoptar esta versión", style="Accent.TButton",
                                       command=self._adopt)
        self.adopt_button.pack(side="left")
        self.locate_button = ttk.Button(footer, text="Localizar el fichero movido…", command=self._locate)
        self.locate_button.pack(side="left", padx=8)
        self.retire_button = ttk.Button(footer, text="Retirar del índice", style="Danger.TButton",
                                        command=self._retire)
        self.retire_button.pack(side="left")
        ttk.Button(footer, text="Cerrar", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda _event: self.destroy())
        self._items: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._items = {str(item["note_id"]): item for item in self.service.issues()}
        for key, item in self._items.items():
            self.tree.insert("", "end", iid=key, text=item["title"], values=(STATE_TEXT.get(item["state"], ""),))
        if self._items:
            first = next(iter(self._items))
            self.tree.selection_set(first)
        self._select()

    def _selected(self) -> dict | None:
        selection = self.tree.selection()
        return self._items.get(selection[0]) if selection else None

    def _select(self) -> None:
        item = self._selected()
        for button in (self.adopt_button, self.locate_button, self.retire_button):
            button.state(["disabled"])
        self._shown_hash = None
        if item is None:
            write_text(self.body, "No hay notas pendientes de resolver." if not self._items
                       else "Selecciona una nota.")
            return
        self.retire_button.state(["!disabled"])
        header = f"{item['title']}\n{item['vault_path']}\n{item['claims']} afirmación(es) afectadas.\n\n"
        if item["state"] == "MISSING":
            self.locate_button.state(["!disabled"])
            write_text(self.body, header + "El fichero no está donde se publicó. Si lo moviste o renombraste en "
                                           "Obsidian, localízalo; si lo borraste a propósito, retíralo del índice.")
            return
        try:
            text, digest = self.service.current_text(item["note_id"])
        except (OSError, LookupError, ValueError) as error:
            write_text(self.body, header + f"No se pudo leer la nota: {error}")
            return
        self._shown_hash = digest
        self.adopt_button.state(["!disabled"])
        write_text(self.body, header + "Contenido actual en Obsidian (esto es lo que se adoptará):\n\n" + text)

    def _adopt(self) -> None:
        item = self._selected()
        if item is None or self._shown_hash is None:
            return
        if not messagebox.askyesno(
            "Adoptar la edición", "Esta versión pasará a ser la oficial: sus afirmaciones anteriores quedan como "
            "histórico y la nota se vuelve a analizar. ¿Continuar?", parent=self):
            return
        try:
            self.service.adopt_external_version(item["note_id"], self._shown_hash)
        except (ValueError, LookupError, OSError) as error:
            messagebox.showerror("No se pudo adoptar", str(error), parent=self)
        self._after_change("Edición adoptada; la nota se está volviendo a analizar.")

    def _locate(self) -> None:
        item = self._selected()
        if item is None:
            return
        chosen = filedialog.askopenfilename(parent=self, title="¿Dónde está ahora la nota?",
                                            initialdir=str(self.service.vault),
                                            filetypes=(("Notas Markdown", "*.md"),))
        if not chosen:
            return
        try:
            state = self.service.relocate(item["note_id"], Path(chosen))
        except (ValueError, LookupError, OSError) as error:
            messagebox.showerror("No se pudo localizar", str(error), parent=self)
            return
        self._after_change("Nota localizada." if state == "IN_SYNC"
                           else "Nota localizada, pero también cambió: revisa la edición y adóptala.")

    def _retire(self) -> None:
        item = self._selected()
        if item is None or not messagebox.askyesno(
                "Retirar del índice", "La nota dejará de consultarse y sus afirmaciones pasarán a histórico. "
                "El fichero y su historial no se borran. ¿Continuar?", parent=self):
            return
        try:
            self.service.retire(item["note_id"])
        except (ValueError, LookupError) as error:
            messagebox.showerror("No se pudo retirar", str(error), parent=self)
            return
        self._after_change("Nota retirada del índice.")

    def _after_change(self, message: str) -> None:
        self.on_change(message)
        self.load()


__all__ = ["NoteReconciliationDialog"]
