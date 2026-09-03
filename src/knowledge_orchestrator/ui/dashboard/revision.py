"""Vista «Revisión»: qué cambios semánticos se incorporan al conocimiento."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from knowledge_orchestrator.ui.dashboard.trabajo import TrabajoMixin


class RevisionMixin(TrabajoMixin):
    """Cola de revisión: listado, detalle y decisión."""

    def _build_review(self) -> None:
        page = self._new_page("review")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        self._page_heading(page, "Revisión", "Decide qué cambios semánticos se incorporan a tu base de conocimiento.")
        columns = ("id", "relacion", "confianza", "impacto", "nota", "estado")
        self.review_tree = ttk.Treeview(page, columns=columns, show="headings", height=8, style="Dark.Treeview")
        for column, text in {
            "id": "ID", "relacion": "Relación", "confianza": "Confianza",
            "impacto": "Impacto", "nota": "Nota", "estado": "Estado",
        }.items():
            self.review_tree.heading(column, text=text)
            self.review_tree.column(column, width=120)
        self.review_tree.grid(row=2, column=0, sticky="nsew", padx=24)
        self.review_tree.bind("<<TreeviewSelect>>", lambda _event: self._select_review())
        self.review_detail = tk.Text(page, height=10, wrap="word", bg=self.colors["raised"], fg=self.colors["text"],
                                     insertbackground=self.colors["text"], relief="flat", padx=12, pady=12)
        self.review_detail.grid(row=3, column=0, sticky="ew", padx=24, pady=(12, 0))
        buttons = tk.Frame(page, bg=self.colors["surface"])
        buttons.grid(row=4, column=0, sticky="e", padx=24, pady=16)
        ttk.Button(
            buttons, text="Aprobar cambio", style="Accent.TButton", command=self._approve_selected
        ).pack(side="left", padx=4)
        ttk.Button(
            buttons, text="Rechazar", style="Danger.TButton", command=self._reject_selected
        ).pack(side="left", padx=4)

    def _refresh_reviews(self) -> None:
        items = self.snapshots.reviews()
        self._review_items = {str(item.candidate_id): item for item in items}
        self._replace_tree(
            self.review_tree,
            [(str(item.candidate_id), (item.candidate_id, item.relation,
              "" if item.confidence is None else f"{item.confidence:.2f}", item.impact,
              item.target_note_id, item.status)) for item in items],
        )

    def _select_review(self) -> None:
        selection = self.review_tree.selection()
        if not selection:
            return
        item = self._review_items.get(str(selection[0]))
        if item is None:
            return
        self._selected_review = item
        self.review_detail.configure(state="normal")
        self.review_detail.delete("1.0", "end")
        self.review_detail.insert(
            "1.0",
            f"Motivo:\n{item.rationale}\n\n"
            f"Cambio propuesto:\n{item.diff_text}\n\n"
            f"Bloqueo: {item.blocked_reason or '—'}",
        )
        self.review_detail.configure(state="disabled")

    def _approve_selected(self) -> None:
        if not self._selected_review:
            return
        try:
            self.runtime.semantic_maintenance.approve(self._selected_review.candidate_id)
        except Exception as error:
            messagebox.showerror("No se pudo aprobar", str(error), parent=self)
        else:
            self.status_var.set(f"Candidato {self._selected_review.candidate_id} aprobado.")
            self._selected_review = None
            self._refresh_reviews()

    def _reject_selected(self) -> None:
        if not self._selected_review:
            return
        try:
            self.runtime.semantic_maintenance.reject(self._selected_review.candidate_id)
        except Exception as error:
            messagebox.showerror("No se pudo rechazar", str(error), parent=self)
        else:
            self.status_var.set(f"Candidato {self._selected_review.candidate_id} rechazado.")
            self._selected_review = None
            self._refresh_reviews()
