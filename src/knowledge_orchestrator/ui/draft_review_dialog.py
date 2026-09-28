"""THESIS: decidir si un borrador se publica después de haberlo leído, no antes.
OWN-WORLD: misma superficie grafito/cian que los demás diálogos; texto a la izquierda, decisión al pie.
STORY: leer el apunte generado, aprobarlo (se publica tal cual se leyó) o descartarlo sin perder nada.
FIRST VIEWPORT: título y estado arriba, el borrador ocupando todo el centro, las dos decisiones al pie.
FORM: diálogo modal. La aprobación va ligada al hash del texto mostrado: si el resultado cambiara
      entretanto, no se aprueba nada (auditoría H01).
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Any

from knowledge_orchestrator.domain.publication_models import DraftForReview
from knowledge_orchestrator.ui.automation_plan import text_panel, write_text


class DraftReviewDialog(tk.Toplevel):
    """Muestra el borrador y registra la decisión de la persona."""

    def __init__(
        self,
        parent: Any,
        draft: DraftForReview,
        *,
        approve: Callable[[str, str], bool],
        reject: Callable[[str], bool],
        on_done: Callable[[str], None],
    ) -> None:
        super().__init__(parent)
        self.draft = draft
        self._approve, self._reject, self._on_done = approve, reject, on_done
        self.decision: str | None = None
        self.title(f"Revisar borrador · {draft.title}")
        self.geometry("920x680")
        self.minsize(640, 480)
        self.transient(parent)
        self.configure(bg=parent.colors["surface"])
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        header = ttk.Label(self, text=draft.title, font=("Segoe UI Semibold", 13), wraplength=860, justify="left")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 2))
        pending = draft.review_status == "PENDING"
        explanation = (
            "El perfil exige revisión humana antes de publicar. Lee el apunte: si lo apruebas se publica "
            "exactamente este texto en la bóveda; si lo descartas, no se publica y se conservan la fuente y "
            "el resultado para volver a procesarlo."
            if pending else
            "Este borrador se descartó. Se conserva para consulta; puedes volver a procesar el documento desde "
            "la pantalla Documentos."
        )
        ttk.Label(self, text=f"Revisión {draft.revision} · {explanation}", wraplength=860,
                  justify="left").grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))
        frame, self.body = text_panel(self, parent.colors)
        frame.grid(row=2, column=0, sticky="nsew", padx=16)
        write_text(self.body, draft.final_result)
        footer = ttk.Frame(self)
        footer.grid(row=3, column=0, sticky="ew", padx=16, pady=12)
        self.approve_button = ttk.Button(footer, text="Aprobar y publicar", style="Accent.TButton",
                                         command=self._on_approve)
        self.approve_button.pack(side="left")
        self.reject_button = ttk.Button(footer, text="Descartar borrador", style="Danger.TButton",
                                        command=self._on_reject)
        self.reject_button.pack(side="left", padx=(8, 0))
        if not pending:
            self.approve_button.state(["disabled"])
            self.reject_button.state(["disabled"])
        ttk.Button(footer, text="Cerrar", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda _event: self.destroy())

    def _on_approve(self) -> None:
        if self._approve(self.draft.workflow_id, self.draft.result_hash):
            self._finish("approved", "Borrador aprobado: se publicará en la bóveda en unos segundos.")
        else:
            messagebox.showwarning(
                "No se pudo aprobar",
                "El borrador cambió o ya se decidió desde otro sitio. Cierra y vuelve a abrirlo.",
                parent=self,
            )

    def _on_reject(self) -> None:
        if not messagebox.askyesno(
            "Descartar borrador",
            "No se publicará. La fuente y el resultado se conservan y podrás volver a procesar el documento. "
            "¿Continuar?",
            parent=self,
        ):
            return
        if self._reject(self.draft.workflow_id):
            self._finish("rejected", "Borrador descartado; la fuente y el resultado se conservan.")
        else:
            messagebox.showwarning("No se pudo descartar", "El borrador ya se decidió desde otro sitio.",
                                   parent=self)

    def _finish(self, decision: str, message: str) -> None:
        self.decision = decision
        self._on_done(message)
        self.destroy()


__all__ = ["DraftReviewDialog"]
