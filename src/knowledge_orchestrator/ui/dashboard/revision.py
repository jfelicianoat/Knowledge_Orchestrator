"""Vista «Revisión»: qué cambios semánticos se incorporan al conocimiento.

La decisión se toma comparando: «Ahora» y «Propuesto» van lado a lado, y
debajo el porqué, la evidencia y los riesgos. Antes era un único bloque de
texto monoespaciado donde el cambio quedaba enterrado entre metadatos.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from knowledge_orchestrator.services.proposal_audit import ProposalAuditReader
from knowledge_orchestrator.ui.dashboard.estilo import FONT, FONT_SEMIBOLD, MONO
from knowledge_orchestrator.ui.dashboard.trabajo import TrabajoMixin
from knowledge_orchestrator.ui.proposal_audit_dialog import ProposalAuditDialog
from knowledge_orchestrator.ui.reversion_panel import ReversionPanel
from knowledge_orchestrator.ui.review_batch_dialog import ReviewBatchDialog
from knowledge_orchestrator.ui.snapshots import ReviewItem

RELATION_LABELS = {
    "SUPPORTS": "Confirma",
    "EXTENDS": "Amplía",
    "CONTRADICTS": "Contradice",
    "SUPERSEDES": "Sustituye",
    "UNRELATED": "Sin relación",
    "UNCERTAIN": "Requiere criterio",
}


def relation_text(relation: str | None) -> str:
    """Rótulo de la relación para leer; «UNKNOWN» es una comparación que aún no se hizo o falló."""

    if relation == "UNKNOWN" or not relation:
        return "Sin comparar"
    return RELATION_LABELS.get(relation, relation)


#: Motivos de bloqueo que se guardan como código; en pantalla salían tal cual.
BLOCK_REASONS = {
    "INCOMPLETE_APPLICATION_INTENT": "La aplicación se interrumpió sin datos suficientes para completarla.",
    "NOTE_CHANGED_AFTER_DIFF": "La nota cambió después de preparar la propuesta.",
    "NOTE_CHANGED_DURING_RECOVERY": "La nota cambió mientras se completaba la aplicación.",
    "NOTE_CHANGED_DURING_APPLICATION": "La nota cambió mientras se aplicaba el cambio.",
    "CONTENT_CHANGED_DURING_APPLICATION": "El contenido cambió mientras se aplicaba el cambio.",
    "CONTENT_CHANGED_DURING_RECOVERY": "La nota o su evidencia cambiaron antes de completar la aplicación.",
    "NOTE_UNREADABLE_DURING_RECOVERY": "No se pudo leer la nota al completar la aplicación.",
    "EVIDENCE_CHANGED_AFTER_DIFF": "La evidencia nueva cambió después de preparar la propuesta.",
    "HUMAN_REJECTED": "Descartada por una persona.",
    "SUCCESSOR_REVERTED": "El cambio se revirtió.",
}


RELATION_TONES = {"SUPPORTS": "success", "EXTENDS": "accent", "CONTRADICTS": "error",
                  "SUPERSEDES": "warning", "UNRELATED": "neutral", "UNCERTAIN": "warning"}

IMPACT_LABELS = {"HIGH": "Alto", "MEDIUM": "Medio", "LOW": "Bajo"}
IMPACT_TONES = {"HIGH": "error", "MEDIUM": "warning", "LOW": "neutral"}
RISK_LABELS = {
    'SOURCE_TRUST_IS_NOT_FACTUAL_PROOF': 'La confianza configurada de una fuente no demuestra el hecho.',
    'MODEL_CONFIDENCE_IS_NOT_FACTUAL_PROOF': 'La confianza del modelo no es verificación factual.',
    'CONFLICTING_EVIDENCE_REQUIRES_HUMAN_REVIEW': 'Las evidencias se contradicen; requieren criterio humano.',
    'HIGH_TRUST_SOURCES_DISAGREE': 'Dos fuentes de alta confianza discrepan.',
    'LOWER_TRUST_SOURCE_DISAGREES': 'La fuente nueva tiene menor confianza y contradice a la anterior.',
    'SEMANTIC_RELATION_UNCERTAIN': 'La relación entre las afirmaciones no está clara.',
    'SOURCE_TRUST_NOT_CONFIGURED': 'Hay fuentes sin confianza configurada.',
}

#: Superficies de la comparación: rojo apagado para lo que sale, verde para lo que entra.
BEFORE_COLORS = ("#1d1417", "#5a2a30", "#ffb3b8")
AFTER_COLORS = ("#12201a", "#2c5a3b", "#9fe6b8")


class RevisionMixin(TrabajoMixin):
    """Cola de revisión: listado, comparación y decisión."""

    def _build_review(self) -> None:
        c = self.colors
        page = self._new_page("review")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self._page_heading(page, "Revisión", "La IA propone cambios; tú decides qué entra en el conocimiento.")
        tabs = ttk.Notebook(page)
        tabs.grid(row=1, column=0, sticky='nsew', padx=28, pady=(0, 20))
        self._review_tabs = tabs
        body = tk.Frame(tabs, bg=c['surface'])
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)
        tabs.add(body, text='Propuestas pendientes')
        tabs.add(ReversionPanel(tabs, self.runtime.maintenance_reversion, self.colors, self._reversion_ready),
                 text='Publicadas y reversión')

        bulk = tk.Frame(body, bg=c['surface'])
        bulk.grid(row=0, column=0, sticky='ew', pady=(14, 10))
        self.review_count_var = tk.StringVar(value='')
        self._text(bulk, textvariable=self.review_count_var, color='muted').pack(side='left')
        ttk.Button(bulk, text='Lotes anteriores', command=lambda: ReviewBatchDialog(
            self, self.runtime.review_batches, history=True)).pack(side='right', padx=(6, 0))
        ttk.Button(bulk, text='Revisar todas las pendientes', command=lambda: ReviewBatchDialog(
            self, self.runtime.review_batches)).pack(side='right', padx=(6, 0))
        ttk.Button(bulk, text='Revisar selección', command=self._preview_review_selection).pack(side='right')

        panes = tk.PanedWindow(body, orient='horizontal', bg=c['border'], sashwidth=1, bd=0, relief='flat')
        panes.grid(row=1, column=0, sticky='nsew')
        left = tk.Frame(panes, bg=c['surface'])
        right = tk.Frame(panes, bg=c['surface'])
        # 380 px no daban para las cuatro columnas: «Impacto» salía como «Alt», «Me».
        panes.add(left, minsize=300, width=430, stretch='never')
        panes.add(right, minsize=520, stretch='always')
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        columns = ("nota", "cambio", "confianza", "impacto")
        self.review_tree = ttk.Treeview(left, columns=columns, show="headings", selectmode='extended')
        for column, text, width in (("nota", "Nota afectada", 170), ("cambio", "Cambio", 90),
                                    ("confianza", "Confianza", 78), ("impacto", "Impacto", 66)):
            self.review_tree.heading(column, text=text)
            self.review_tree.column(column, width=width, minwidth=60, stretch=column == "nota")
        self.review_tree.grid(row=0, column=0, sticky="nsew")
        self.review_tree.tag_configure('HIGH', foreground='#ff9aa0')
        self.review_tree.tag_configure('CONFLICT', foreground='#f5c56b')
        self.review_tree.bind("<<TreeviewSelect>>", lambda _event: self._select_review())
        scroll = ttk.Scrollbar(left, orient='vertical', command=self.review_tree.yview)
        scroll.grid(row=0, column=1, sticky='ns', padx=(0, 10))
        self.review_tree.configure(yscrollcommand=scroll.set)
        self._text(left, 'Ctrl o Mayús para seleccionar varias y revisarlas en lote.', size=8, color='faint').grid(
            row=1, column=0, sticky='w', pady=(8, 0))

        # Las acciones van bajo el título y no al pie: a 1080×680 el pie quedaba
        # fuera de la ventana y no se podía aplicar ni descartar.
        right.columnconfigure(0, weight=1)
        right.rowconfigure(4, weight=1)
        self.review_title_var = tk.StringVar(value='Selecciona una propuesta')
        self._text(right, textvariable=self.review_title_var, size=15, bold=True, wraplength=640).grid(
            row=0, column=0, sticky='ew', padx=(22, 10), pady=(4, 6))
        pills = tk.Frame(right, bg=c['surface'])
        pills.grid(row=1, column=0, sticky='w', padx=22, pady=(0, 10))
        self.review_relation_pill = self._pill(pills)
        self.review_confidence_pill = self._pill(pills)
        self.review_impact_pill = self._pill(pills)
        for pill in (self.review_relation_pill, self.review_confidence_pill, self.review_impact_pill):
            pill.pack(side='left', padx=(0, 6))

        compare = tk.Frame(right, bg=c['surface'])
        compare.grid(row=3, column=0, sticky='ew', padx=22)
        compare.columnconfigure((0, 1), weight=1, uniform='compare')
        self.review_before = self._comparison_box(compare, 0, 'Ahora', BEFORE_COLORS)
        self.review_after = self._comparison_box(compare, 1, 'Propuesto', AFTER_COLORS)

        self.review_detail = tk.Text(right, height=10, wrap="word", bg=c["raised"], fg=c["muted"],
                                     insertbackground=c["text"], relief="flat", padx=16, pady=10,
                                     font=(FONT, 10), highlightthickness=0, cursor='arrow')
        self.review_detail.grid(row=4, column=0, sticky="nsew", padx=22, pady=(12, 14))
        self.review_detail.tag_configure('h', foreground=c['text'], font=(FONT_SEMIBOLD, 10), spacing1=10,
                                         spacing3=2)
        self.review_detail.tag_configure('risk', foreground='#f5c56b')
        self.review_detail.tag_configure('mono', font=(MONO, 9), foreground=c['muted'])
        self.review_detail.tag_configure('meta', foreground=c['faint'], font=(FONT, 9), spacing1=12)

        # Dos filas: la decisión (aplicar, editar, descartar) arriba y las
        # consultas debajo. En una sola fila, a 1080 px «Descartar» quedaba fuera.
        buttons = tk.Frame(right, bg=c["surface"])
        buttons.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 12))
        decision = tk.Frame(buttons, bg=c["surface"])
        decision.pack(fill="x")
        self.review_approve_button = ttk.Button(
            decision, text="✓  Aplicar cambio", style="Accent.TButton", command=self._approve_selected
        )
        self.review_approve_button.pack(side="left", padx=(0, 6))
        self.review_edit_button = ttk.Button(decision, text='Editar', command=self._edit_selected_review)
        self.review_edit_button.pack(side='left', padx=(0, 6))
        self.review_reject_button = ttk.Button(
            decision, text="Descartar", style="Danger.TButton", command=self._reject_selected
        )
        self.review_reject_button.pack(side="left")
        inquiry = tk.Frame(buttons, bg=c["surface"])
        inquiry.pack(fill="x", pady=(6, 0))
        self.review_audit_button = ttk.Button(inquiry, text='Ver trazabilidad', command=self._audit_selected_review)
        self.review_audit_button.pack(side='left', padx=(0, 6))
        self.review_policy_button = ttk.Button(inquiry, text='Evaluar con política',
                                               command=self._evaluate_selected_policy)
        self.review_policy_button.pack(side='left')
        # Por qué no se puede aplicar, junto al botón: antes solo lo decía el
        # texto de «Restricción», abajo del todo (auditoría 14-oct I-01c).
        self.review_block_var = tk.StringVar(value='')
        tk.Label(buttons, textvariable=self.review_block_var, bg=c['surface'], fg=c['warning'], font=(FONT, 9),
                 anchor='w', justify='left', wraplength=620).pack(fill='x', pady=(6, 0))
        for button in (self.review_approve_button, self.review_reject_button, self.review_edit_button,
                       self.review_policy_button, self.review_audit_button):
            button.state(['disabled'])

    def _comparison_box(self, parent: tk.Frame, column: int, title: str, palette: tuple[str, str, str]) -> tk.Text:
        background, border, foreground = palette
        box = tk.Frame(parent, bg=background, highlightbackground=border, highlightthickness=1)
        box.grid(row=0, column=column, sticky='nsew', padx=(0, 6) if column == 0 else (6, 0))
        tk.Label(box, text=title, bg=background, fg=self.colors['text'], font=(FONT_SEMIBOLD, 10),
                 anchor='w').pack(fill='x', padx=14, pady=(10, 2))
        tk.Frame(box, bg=border, height=1).pack(fill='x')
        text = tk.Text(box, height=6, wrap='word', bg=background, fg=foreground, relief='flat', padx=14, pady=10,
                       font=(FONT, 10), highlightthickness=0, cursor='arrow', state='disabled')
        text.pack(fill='both', expand=True)
        return text

    @staticmethod
    def _fill_text(widget: tk.Text, value: str) -> None:
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', value)
        widget.configure(state='disabled')

    def _reversion_ready(self):
        startup = getattr(self, '_startup', None)
        return bool(startup and startup.done and startup.error is None)

    def _refresh_reviews(self) -> None:
        previous = self.review_tree.selection()
        focus = self.review_tree.focus()
        items = self.snapshots.reviews()
        self._review_items = {str(item.candidate_id): item for item in items}
        rows = [
            (
                str(item.candidate_id),
                (
                    item.target_title,
                    # En la lista se veía «UNKNOWN» y un conflicto no se distinguía.
                    "En conflicto" if item.status == "CONFLICT" else "Aplicándose" if item.status == "APPLYING"
                    else relation_text(item.relation),
                    "—" if item.confidence is None else f"{item.confidence:.0%}",
                    IMPACT_LABELS.get(item.impact, item.impact or "—"),
                ),
            )
            for item in items
        ]
        self._replace_tree(
            self.review_tree,
            rows,
            tags={str(item.candidate_id): ((item.status,) if item.status == 'CONFLICT' else (item.impact,))
                  for item in items},
        )
        count = len(items)
        self.review_count_var.set(
            f"{count} propuesta{'s' if count != 1 else ''} esperando tu decisión" if count
            else "No hay propuestas pendientes."
        )
        self._review_tabs.tab(0, text=f"Propuestas pendientes  {count}" if count else "Propuestas pendientes")
        preserved = [identifier for identifier in previous if identifier in self._review_items]
        if preserved:
            self._keep_selection(self.review_tree, preserved)
            selected_id = focus if focus in preserved else preserved[0]
            self.review_tree.focus(selected_id)
            self._render_review(self._review_items[selected_id])
        else:
            self._clear_review(empty=not items)

    def _select_review(self) -> None:
        selection = self.review_tree.selection()
        if not selection:
            self._clear_review(empty=not self._review_items)
            return
        focused = self.review_tree.focus()
        item = self._review_items.get(str(focused if focused in selection else selection[0]))
        if item is None:
            return
        self._selected_review = item
        self._render_review(item)

    def _render_review(self, item: ReviewItem) -> None:
        self._selected_review = item
        detail = self.runtime.semantic_maintenance.proposal_detail(item.candidate_id)
        assessment = detail['assessment'] or {}
        relation = relation_text(item.relation)
        self.review_title_var.set(f"Actualizar «{item.target_title}»")
        self._set_pill(self.review_relation_pill, relation, tone=RELATION_TONES.get(item.relation, 'neutral'))
        self._set_pill(self.review_confidence_pill,
                       'Confianza no disponible' if item.confidence is None else f'Confianza {item.confidence:.0%}',
                       tone='accent')
        self._set_pill(self.review_impact_pill,
                       f"Impacto {IMPACT_LABELS.get(item.impact, item.impact or 'sin estimar').lower()}",
                       tone=IMPACT_TONES.get(item.impact, 'neutral'))
        for pill in (self.review_relation_pill, self.review_confidence_pill, self.review_impact_pill):
            pill.pack(side='left', padx=(0, 6))
        self._fill_text(self.review_before, assessment.get('before') or 'Sin evaluación guardada.')
        self._fill_text(self.review_after, assessment.get('proposed') or 'Sin reemplazo documental.')

        sources = '\n'.join(
            f"{e['source']['title']} · {e['source'].get('source_url', 'Documento local')} · "
            'Confianza configurada: ' + str(e['source'].get('monitoring', {}).get('trust_level', 'sin dato'))
            for e in assessment.get('evidence', []))
        risks = [RISK_LABELS.get(risk, risk) for risk in assessment.get('risks', [])]
        text = self.review_detail
        text.configure(state='normal')
        text.delete('1.0', 'end')
        text.insert('end', 'Por qué\n', 'h')
        text.insert('end', (item.rationale or 'No se proporcionó una explicación.') + '\n')
        text.insert('end', 'Evidencia\n', 'h')
        text.insert('end', (sources or 'Sin fuentes registradas.') + '\n')
        text.insert('end', 'Riesgos e incertidumbres\n', 'h')
        if risks:
            for risk in risks:
                text.insert('end', f'▲  {risk}\n', 'risk')
        else:
            text.insert('end', 'Ninguno registrado.\n')
        text.insert('end', 'Restricción\n', 'h')
        conflict = item.status == 'CONFLICT'
        applying = item.status == 'APPLYING'
        editor_ready = self.runtime.semantic_maintenance.editor_ready()
        restriction = (BLOCK_REASONS.get(item.blocked_reason or '', item.blocked_reason)
                       or 'Ninguna. Puedes aplicar o descartar la propuesta.')
        if applying:
            restriction = ('Aprobada y pendiente de escribirse en la nota. Se completará sola en cuanto el puente '
                           'de Obsidian esté disponible (al arrancar o reintentar). '
                           + ('' if editor_ready else self.runtime.semantic_maintenance.EDITOR_MISSING))
        elif not editor_ready and not conflict:
            restriction = self.runtime.semantic_maintenance.EDITOR_MISSING
        if conflict:
            # La nota cambió por debajo: la propuesta ya no puede aplicarse ni
            # editarse (antes «Editar» fallaba con «El span objetivo no conserva
            # su evidencia»). Se dice qué hacer en lugar de dejar probar.
            restriction += ('\nEsta propuesta ya no se puede aplicar ni editar: descártala. Si el cambio sigue '
                            'procediendo, el nuevo análisis de la nota generará una propuesta nueva.')
        text.insert('end', restriction + '\n')
        text.insert('end', 'Histórico\n', 'h')
        text.insert('end', assessment.get('expected_effect', 'Requiere regeneración') + '\n')
        text.insert('end', 'Autoaprobación\n', 'h')
        text.insert('end', detail['automation_review']['message'] + '\n')
        text.insert('end', 'Vista previa del cambio en la nota\n', 'h')
        text.insert('end', (item.diff_text or 'No hay diferencias disponibles.') + '\n', 'mono')
        text.insert('end', f"Nota: {item.target_path or item.target_title} · "
                           f"Revisión de propuesta: {item.proposal_revision}", 'meta')
        text.configure(state='disabled')
        self.review_reject_button.state(['disabled'] if applying else ["!disabled"])
        self.review_edit_button.state(['disabled'] if conflict or applying else ['!disabled'])
        self.review_policy_button.state(['disabled'] if conflict or applying else ['!disabled'])
        self.review_audit_button.state(['!disabled'])
        blocked = (item.status != 'PENDING_REVIEW' or item.blocked_reason or not editor_ready
                   or assessment.get('blockers') or not assessment.get('patch'))
        self.review_approve_button.state(['disabled'] if blocked else ['!disabled'])
        reason = ''
        if blocked and item.status in {'PENDING_REVIEW', 'CONFLICT'}:
            reason = (restriction.splitlines()[0] if item.blocked_reason or not editor_ready or conflict
                      else 'La evaluación no dejó un cambio aplicable: edítala o descártala.')
        self.review_block_var.set(f'No se puede aplicar. {reason}' if reason else '')

    def _clear_review(self, *, empty: bool = False) -> None:
        self._selected_review = None
        self.review_title_var.set('No hay propuestas pendientes' if empty else 'Selecciona una propuesta')
        for pill in (self.review_relation_pill, self.review_confidence_pill, self.review_impact_pill):
            pill.pack_forget()
        self._fill_text(self.review_before, '')
        self._fill_text(self.review_after, '')
        self._fill_text(
            self.review_detail,
            (
                "Cuando la IA detecte que un documento nuevo confirma, amplía o contradice una nota "
                "publicada, la propuesta aparecerá aquí para que decidas."
                if empty
                else "Selecciona una propuesta para comparar la evidencia y el cambio antes de decidir."
            ),
        )
        self.review_approve_button.state(["disabled"])
        self.review_block_var.set('')
        self.review_reject_button.state(["disabled"])
        self.review_edit_button.state(['disabled'])
        self.review_policy_button.state(['disabled'])
        self.review_audit_button.state(['disabled'])

    def _audit_selected_review(self):
        if self._selected_review:
            self._open_proposal_audit(self._selected_review.candidate_id)

    def _open_proposal_audit(self, candidate_id: int):
        ProposalAuditDialog(self, ProposalAuditReader(self.runtime.database), candidate_id)

    def _evaluate_selected_policy(self):
        if self._selected_review:
            item = self._selected_review
            self._review_proposal_policy(item.candidate_id, item.proposal_revision)

    def _approve_selected(self) -> None:
        if not self._selected_review:
            return
        item = self._selected_review
        ReviewBatchDialog(self, self.runtime.review_batches, selection=[{
            'candidate_id': item.candidate_id, 'expected_revision': item.proposal_revision}])

    def _preview_review_selection(self) -> None:
        selection = [self._review_items[identifier] for identifier in self.review_tree.selection()
                     if identifier in self._review_items]
        if not selection:
            self.status_var.set('Selecciona propuestas con Ctrl o Mayús para preparar su vista previa.')
            return
        ReviewBatchDialog(self, self.runtime.review_batches, selection=[{
            'candidate_id': item.candidate_id, 'expected_revision': item.proposal_revision} for item in selection])

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
        dialog.configure(background=self.colors['surface'])
        dialog.columnconfigure(0, weight=1)
        relation = tk.StringVar(value=RELATION_LABELS.get(candidate.relation, 'Requiere criterio'))
        ttk.Label(dialog, text='Relación propuesta').grid(row=0, column=0, sticky='w', padx=16, pady=8)
        ttk.Combobox(dialog, values=list(RELATION_LABELS.values()), textvariable=relation,
                     state='readonly', width=45).grid(row=1, column=0, sticky='ew', padx=16)
        ttk.Label(dialog, text='Justificación breve basada en la evidencia').grid(
            row=2, column=0, sticky='w', padx=16, pady=8)
        rationale = tk.Text(dialog, width=70, height=4, wrap='word', padx=8, pady=6)
        rationale.grid(row=3, column=0, sticky='ew', padx=16)
        rationale.insert('1.0', candidate.rationale or '')
        ttk.Label(dialog, text='Texto propuesto: conserva la cita original, sin añadir hechos inferidos.').grid(
            row=4, column=0, sticky='w', padx=16, pady=8)
        replacement = tk.Text(dialog, width=70, height=5, wrap='word', padx=8, pady=6)
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

        # Modal y con «Cancelar»: un segundo clic en «Editar» abría otra copia encima (auditoría 14-oct I-06).
        actions = ttk.Frame(dialog)
        actions.grid(row=6, column=0, sticky='e', padx=16, pady=16)
        ttk.Button(actions, text='Cancelar', command=dialog.destroy).pack(side='right')
        ttk.Button(actions, text='Guardar nueva revisión', style='Accent.TButton', command=save).pack(
            side='right', padx=(0, 8))
        dialog.bind('<Escape>', lambda _event: dialog.destroy())
        dialog.grab_set()
