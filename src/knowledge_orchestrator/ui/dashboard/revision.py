"""Vista «Revisión»: qué cambios semánticos se incorporan al conocimiento."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from knowledge_orchestrator.ui.dashboard.trabajo import TrabajoMixin
from knowledge_orchestrator.ui.snapshots import ReviewItem

RELATION_LABELS = {
    "SUPPORTS": "Confirma",
    "EXTENDS": "Amplía",
    "CONTRADICTS": "Contradice",
    "SUPERSEDES": "Sustituye",
    "UNRELATED": "Sin relación",
    "UNCERTAIN": "Requiere criterio",
}

IMPACT_LABELS = {"HIGH": "Alto", "MEDIUM": "Medio", "LOW": "Bajo"}
RISK_LABELS = {
    'SOURCE_TRUST_IS_NOT_FACTUAL_PROOF': 'La confianza configurada de una fuente no demuestra el hecho.',
    'MODEL_CONFIDENCE_IS_NOT_FACTUAL_PROOF': 'La confianza del modelo no es verificación factual.',
    'CONFLICTING_EVIDENCE_REQUIRES_HUMAN_REVIEW': 'Las evidencias se contradicen; requieren criterio humano.',
    'HIGH_TRUST_SOURCES_DISAGREE': 'Dos fuentes de alta confianza discrepan.',
    'LOWER_TRUST_SOURCE_DISAGREES': 'La fuente nueva tiene menor confianza y contradice a la anterior.',
    'SEMANTIC_RELATION_UNCERTAIN': 'La relación entre las afirmaciones no está clara.',
    'SOURCE_TRUST_NOT_CONFIGURED': 'Hay fuentes sin confianza configurada.',
}


class RevisionMixin(TrabajoMixin):
    """Cola de revisión: listado, detalle y decisión."""

    def _build_review(self) -> None:
        page = self._new_page("review")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        self._page_heading(
            page,
            "Revisión",
            "Compara la evidencia nueva antes de modificar el conocimiento publicado.",
        )
        columns = ("cambio", "confianza", "impacto", "nota")
        self.review_tree = ttk.Treeview(page, columns=columns, show="headings", height=8, style="Dark.Treeview")
        for column, text in {
            "cambio": "Cambio propuesto", "confianza": "Confianza",
            "impacto": "Impacto", "nota": "Nota afectada",
        }.items():
            self.review_tree.heading(column, text=text)
            self.review_tree.column(column, width=190 if column == "cambio" else 130)
        self.review_tree.grid(row=2, column=0, sticky="nsew", padx=24)
        self.review_tree.bind("<<TreeviewSelect>>", lambda _event: self._select_review())
        self.review_detail = tk.Text(page, height=10, wrap="word", bg=self.colors["raised"], fg=self.colors["text"],
                                     insertbackground=self.colors["text"], relief="flat", padx=12, pady=12)
        self.review_detail.grid(row=3, column=0, sticky="ew", padx=24, pady=(12, 0))
        buttons = tk.Frame(page, bg=self.colors["surface"])
        buttons.grid(row=4, column=0, sticky="e", padx=24, pady=16)
        self.review_approve_button = ttk.Button(
            buttons, text="Aplicar cambio", style="Accent.TButton", command=self._approve_selected
        )
        self.review_approve_button.pack(side="left", padx=4)
        self.review_reject_button = ttk.Button(
            buttons, text="Descartar propuesta", style="Danger.TButton", command=self._reject_selected
        )
        self.review_reject_button.pack(side="left", padx=4)
        self.review_edit_button = ttk.Button(buttons, text='Editar propuesta', command=self._edit_selected_review)
        self.review_edit_button.pack(side='left', padx=4)
        self.review_approve_button.state(["disabled"])
        self.review_reject_button.state(["disabled"])
        self.review_edit_button.state(['disabled'])

    def _refresh_reviews(self) -> None:
        items = self.snapshots.reviews()
        self._review_items = {str(item.candidate_id): item for item in items}
        rows = [
            (
                str(item.candidate_id),
                (
                    RELATION_LABELS.get(item.relation, item.relation),
                    "—" if item.confidence is None else f"{item.confidence:.0%}",
                    IMPACT_LABELS.get(item.impact, item.impact or "—"),
                    item.target_title,
                ),
            )
            for item in items
        ]
        self._replace_tree(
            self.review_tree,
            rows,
        )
        selected_id = str(self._selected_review.candidate_id) if self._selected_review else ""
        if selected_id in self._review_items:
            self.review_tree.selection_set(selected_id)
            self._render_review(self._review_items[selected_id])
        else:
            self._clear_review(empty=not items)

    def _select_review(self) -> None:
        selection = self.review_tree.selection()
        if not selection:
            self._clear_review(empty=not self._review_items)
            return
        item = self._review_items.get(str(selection[0]))
        if item is None:
            return
        self._selected_review = item
        self._render_review(item)

    def _render_review(self, item: ReviewItem) -> None:
        self._selected_review = item
        detail = self.runtime.semantic_maintenance.proposal_detail(item.candidate_id)
        assessment = detail['assessment'] or {}
        self.review_detail.configure(state="normal")
        self.review_detail.delete("1.0", "end")
        self.review_detail.insert(
            "1.0",
            f"Qué propone\n{RELATION_LABELS.get(item.relation, item.relation)} información de «{item.target_title}». "
            f"Impacto {IMPACT_LABELS.get(item.impact, item.impact or 'sin estimar').lower()}"
            f" y confianza {'no disponible' if item.confidence is None else f'{item.confidence:.0%}'}.\n\n"
            f"Nota afectada\n{item.target_path or item.target_title}\n\n"
            f"Por qué\n{item.rationale or 'No se proporcionó una explicación.'}\n\n"
            f"Vista previa del cambio\n{item.diff_text or 'No hay diferencias disponibles.'}\n\n"
            f"Restricción\n{item.blocked_reason or 'Ninguna. Puedes aplicar o descartar la propuesta.'}",
        )
        self.review_detail.insert('end', '\n\nEvidencia anterior\n'
                                  + assessment.get('before', 'Sin evaluación guardada')
                                  + '\n\nPropuesto\n' + (assessment.get('proposed') or 'Sin reemplazo documental')
                                  + '\n\nFuentes\n' + '\n'.join(
                                      f"{e['source']['title']} · {e['source'].get('source_url', 'Documento local')} · "
                                      'Confianza configurada: '
                                      + str(e['source'].get('monitoring', {}).get('trust_level', 'sin dato'))
                                      for e in assessment.get('evidence', []))
                                  + '\n\nHistórico\n' + assessment.get('expected_effect', 'Requiere regeneración')
                                  + '\n\nRiesgos e incertidumbres\n' + '\n'.join(
                                      RISK_LABELS.get(risk, risk) for risk in assessment.get('risks', []))
                                  + f"\n\nRevisión de propuesta: {item.proposal_revision}")
        self.review_detail.configure(state='disabled')
        self.review_reject_button.state(["!disabled"])
        self.review_edit_button.state(['!disabled'])
        blocked = (item.status != 'PENDING_REVIEW' or item.blocked_reason
                   or assessment.get('blockers') or not assessment.get('patch'))
        self.review_approve_button.state(['disabled'] if blocked else ['!disabled'])

    def _clear_review(self, *, empty: bool = False) -> None:
        self._selected_review = None
        self.review_detail.configure(state="normal")
        self.review_detail.delete("1.0", "end")
        self.review_detail.insert(
            "1.0",
            (
                "No hay propuestas pendientes de revisión."
                if empty
                else "Selecciona una propuesta para comparar la evidencia y el cambio antes de decidir."
            ),
        )
        self.review_detail.configure(state="disabled")
        self.review_approve_button.state(["disabled"])
        self.review_reject_button.state(["disabled"])
        self.review_edit_button.state(['disabled'])

    def _approve_selected(self) -> None:
        if not self._selected_review:
            return
        item = self._selected_review
        candidate_id = item.candidate_id
        if not messagebox.askyesno(
            "Aplicar cambio",
            f"Se actualizará «{item.target_title}» conservando su revisión anterior. ¿Quieres continuar?",
            parent=self,
        ):
            return
        try:
            self.runtime.semantic_maintenance.approve(candidate_id,
                                                     expected_revision=item.proposal_revision, actor='ui')
        except Exception as error:
            messagebox.showerror("No se pudo aprobar", str(error), parent=self)
        else:
            self.status_var.set(f"Cambio {candidate_id} aplicado; la revisión anterior se conserva.")
            self._clear_review()
            self._refresh_reviews()

    def _reject_selected(self) -> None:
        if not self._selected_review:
            return
        item = self._selected_review
        candidate_id = item.candidate_id
        if not messagebox.askyesno(
            "Descartar propuesta",
            f"«{item.target_title}» no se modificará y la propuesta quedará registrada como descartada. "
            "¿Continuar?",
            parent=self,
        ):
            return
        try:
            self.runtime.semantic_maintenance.reject(candidate_id, expected_revision=item.proposal_revision, actor='ui')
        except Exception as error:
            messagebox.showerror("No se pudo rechazar", str(error), parent=self)
        else:
            self.status_var.set(f"Propuesta {candidate_id} descartada; la nota no se modificó.")
            self._clear_review()
            self._refresh_reviews()

    def _edit_selected_review(self) -> None:
        if not self._selected_review:
            return
        item = self._selected_review
        candidate = self.runtime.semantic_repository.get_candidate(item.candidate_id)
        if candidate is None:
            return
        dialog = tk.Toplevel(self)
        dialog.title('Editar propuesta con evidencia')
        dialog.transient(self)
        dialog.columnconfigure(0, weight=1)
        relation = tk.StringVar(value=RELATION_LABELS.get(candidate.relation, 'Requiere criterio'))
        ttk.Label(dialog, text='Relación propuesta').grid(row=0, column=0, sticky='w', padx=16, pady=8)
        ttk.Combobox(dialog, values=list(RELATION_LABELS.values()), textvariable=relation,
                     state='readonly', width=45).grid(row=1, column=0, sticky='ew', padx=16)
        ttk.Label(dialog, text='Justificación breve basada en la evidencia').grid(
            row=2, column=0, sticky='w', padx=16, pady=8)
        rationale = tk.Text(dialog, width=70, height=4, wrap='word')
        rationale.grid(row=3, column=0, sticky='ew', padx=16)
        rationale.insert('1.0', candidate.rationale or '')
        ttk.Label(dialog, text='Texto propuesto: conserva la cita original, sin añadir hechos inferidos.').grid(
            row=4, column=0, sticky='w', padx=16, pady=8)
        replacement = tk.Text(dialog, width=70, height=5, wrap='word')
        replacement.grid(row=5, column=0, sticky='ew', padx=16)
        replacement.insert('1.0', candidate.replacement_text or
                           self.runtime.semantic_repository.evidence_quote(candidate.new_claim_id))

        def save():
            selected_relation = next(code for code, label in RELATION_LABELS.items() if label == relation.get())
            payload = {'relation': selected_relation, 'confidence': candidate.confidence or 0.0,
                       'impact': candidate.impact or 'MEDIUM', 'rationale': rationale.get('1.0', 'end-1c'),
                       'replacement_text': replacement.get('1.0', 'end-1c')
                       if selected_relation in {'SUPERSEDES', 'EXTENDS', 'CONTRADICTS'} else None}
            try:
                self.runtime.semantic_maintenance.edit(item.candidate_id, payload,
                                                       expected_revision=item.proposal_revision, actor='ui')
            except (ValueError, RuntimeError) as error:
                messagebox.showerror('No se pudo guardar la propuesta', str(error), parent=dialog)
                return
            dialog.destroy()
            self._refresh_reviews()

        ttk.Button(dialog, text='Guardar nueva revisión', command=save).grid(
            row=6, column=0, sticky='e', padx=16, pady=16)
