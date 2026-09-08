"""Revisión humana del plan fijado; I/O en segundo plano y widgets solo en Tk."""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import uuid
from tkinter import messagebox, ttk

from knowledge_orchestrator.services.review_batches import ReviewBatchService

STATUSES = {'DRAFT': 'Pendiente de confirmar', 'READY': 'En cola', 'RUNNING': 'Aplicando',
            'RECOVERY_REQUIRED': 'Interrumpido · se recuperará al reiniciar la aplicación',
            'COMPLETE': 'Finalizado', 'PENDING': 'Pendiente', 'SKIPPED': 'Excluida',
            'APPLIED': 'Aplicada', 'CONFLICT': 'Conflicto', 'FAILED': 'Error',
            'EXTERNALLY_RESOLVED': 'Resuelta fuera del lote'}


class ReviewBatchDialog(tk.Toplevel):
    def __init__(self, parent, service: ReviewBatchService, *, selection: list[dict] | None = None,
                 history: bool = False) -> None:
        super().__init__(parent)
        self.service = service
        self.colors = parent.colors
        self.batch: dict | None = None
        self._busy = False
        self._closed = False
        self._history = history
        self._offset = 0
        self._history_count = 0
        self._next_refresh = 0.0
        self._history_ids: dict[str, str] = {}
        self._results: queue.SimpleQueue = queue.SimpleQueue()
        self._poll_id: str | None = None
        self.title('Revisión por lotes')
        self.geometry('1080x750')
        self.minsize(800, 600)
        self.configure(bg=self.colors['surface'])
        self.transient(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self.rowconfigure(5, weight=2)
        self.status = tk.StringVar(value='Cargando lotes…' if history else 'Comprobando propuestas y evidencias…')
        tk.Label(self, text='Revisión por lotes', bg=self.colors['surface'], fg=self.colors['text'],
                 font=('Segoe UI', 19, 'bold')).grid(row=0, column=0, sticky='w', padx=20, pady=(16, 6))
        tk.Label(self, textvariable=self.status, bg=self.colors['surface'], fg=self.colors['text'],
                 wraplength=950, justify='left').grid(row=1, column=0, sticky='ew', padx=20, pady=(0, 8))
        history_bar = ttk.Frame(self)
        history_bar.grid(row=2, column=0, sticky='ew', padx=20, pady=4)
        history_bar.columnconfigure(0, weight=1)
        self.history_choice = ttk.Combobox(history_bar, state='readonly')
        self.history_choice.grid(row=0, column=0, sticky='ew')
        self.history_choice.bind('<<ComboboxSelected>>', self._choose_history)
        self.previous = ttk.Button(history_bar, text='Más recientes', command=lambda: self._history_page(-100))
        self.previous.grid(row=0, column=1, padx=4)
        self.next = ttk.Button(history_bar, text='Más antiguos', command=lambda: self._history_page(100))
        self.next.grid(row=0, column=2)
        if not history:
            history_bar.grid_remove()
        self.tree = ttk.Treeview(self, columns=('note', 'status', 'reason'), show='headings',
                                 selectmode='browse', height=7, style='Dark.Treeview')
        for column, title, width in [('note', 'Nota / propuesta', 300), ('status', 'Resultado', 150),
                                     ('reason', 'Acción o motivo', 500)]:
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width)
        self.tree.grid(row=3, column=0, sticky='nsew', padx=(20, 36))
        scroll = ttk.Scrollbar(self, orient='vertical', command=self.tree.yview)
        scroll.grid(row=3, column=0, sticky='nse', padx=(0, 20))
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>', lambda _event: self._detail())
        self.explanation = tk.StringVar(value='Selecciona una propuesta para revisar el cambio y sus fuentes.')
        tk.Label(self, textvariable=self.explanation, bg=self.colors['surface'], fg=self.colors['text'],
                 wraplength=950, justify='left').grid(row=4, column=0, sticky='ew', padx=20, pady=8)
        panes = ttk.Panedwindow(self, orient='horizontal')
        panes.grid(row=5, column=0, sticky='nsew', padx=20)
        self.before = self._text_panel(panes, 'Antes')
        self.proposed = self._text_panel(panes, 'Después · conserva el histórico')
        self.evidence = tk.Text(self, height=5, wrap='word', bg=self.colors['raised'], fg=self.colors['text'],
                                relief='flat', padx=10, pady=8, state='disabled')
        self.evidence.grid(row=6, column=0, sticky='ew', padx=20, pady=8)
        actions = ttk.Frame(self)
        actions.grid(row=7, column=0, sticky='e', padx=20, pady=(4, 16))
        self.confirm_button = ttk.Button(actions, text='Confirmar cambios elegibles', style='Accent.TButton',
                                         command=self._confirm, state='disabled')
        self.confirm_button.pack(side='left', padx=8)
        ttk.Button(actions, text='Cerrar', command=self._close).pack(side='left')
        self.protocol('WM_DELETE_WINDOW', self._close)
        self.bind('<Escape>', lambda _event: self._close())
        self._poll_id = self.after(100, self._poll)
        if history:
            self._load_history()
        else:
            key = uuid.uuid4().hex
            self._submit('batch', lambda: service.preview(owner='ui', key=key, selection=selection))

    def _text_panel(self, panes, title):
        frame = ttk.Frame(panes)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        ttk.Label(frame, text=title).grid(row=0, column=0, sticky='w', pady=(0, 4))
        widget = tk.Text(frame, wrap='word', bg=self.colors['raised'], fg=self.colors['text'],
                         relief='flat', padx=10, pady=8, state='disabled', width=40)
        widget.grid(row=1, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(frame, orient='vertical', command=widget.yview)
        scroll.grid(row=1, column=1, sticky='ns')
        widget.configure(yscrollcommand=scroll.set)
        panes.add(frame, weight=1)
        return widget

    @staticmethod
    def _write(widget, text):
        if widget.get('1.0', 'end-1c') == text:
            return
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', text)
        widget.configure(state='disabled')

    def _submit(self, kind, operation):
        if self._busy or self._closed:
            return
        self._busy = True
        self.confirm_button.state(['disabled'])
        self.history_choice.configure(state='disabled')
        self.previous.state(['disabled'])
        self.next.state(['disabled'])
        results = self._results

        def work():
            try:
                results.put((kind, operation(), None))
            except Exception as error:
                results.put((kind, None, str(error) if isinstance(error, ValueError)
                             else 'No se pudo completar la operación; el estado guardado se conserva.'))

        threading.Thread(target=work, name='review-preview', daemon=True).start()

    def _poll(self):
        if self._closed:
            return
        try:
            kind, result, error = self._results.get_nowait()
        except queue.Empty:
            pass
        else:
            self._busy = False
            self._next_refresh = time.monotonic() + 1
            if error:
                self.status.set(error)
            elif kind == 'history':
                self._history_count = len(result)
                self._history_ids = {
                    f"{row['created_at']} · {STATUSES[row['status']]} · {row['batch_id'][:8]}": row['batch_id']
                    for row in result}
                self.history_choice.configure(values=list(self._history_ids))
                self.history_choice.set('Selecciona un lote' if result else 'No hay lotes en esta página')
                self.status.set(f'Lotes {self._offset + 1}–{self._offset + len(result)}' if result
                                else 'No hay lotes guardados en esta página.')
            else:
                self.batch = result
                self._render()
            self.history_choice.configure(state='readonly')
            self.previous.state(['!disabled'] if self._offset else ['disabled'])
            self.next.state(['!disabled'] if self._history_count == 100 else ['disabled'])
        if not self._busy and time.monotonic() >= self._next_refresh and self.batch \
                and self.batch['status'] in {'READY', 'RUNNING'}:
            batch_id = self.batch['batch_id']
            self._submit('batch', lambda: self.service.repository.get(batch_id, owner='ui'))
        self._poll_id = self.after(1000, self._poll)

    def _render(self):
        batch = self.batch
        if batch is None:
            return
        counts = batch['plan']['counts']
        self.status.set(f"{STATUSES[batch['status']]} · {counts['eligible_tasks']} de {counts['tasks']} propuestas "
                        f"elegibles · {counts['notes']} notas · {counts['existing_claims']} afirmaciones anteriores "
                        f"· {counts['new_claims']} sucesoras. "
                        + ' · '.join(f'{STATUSES[k]}: {v}' for k, v in batch['results'].items()))
        current_ids = set(self.tree.get_children())
        for item, receipt in zip(batch['plan']['items'], batch['items'], strict=True):
            identifier = str(item['candidate_id'])
            result = receipt['result'] or {}
            reason = result.get('reason') or '; '.join(result.get('reasons', item['blockers'])) or item['action']
            values = (f"{item.get('title', 'Propuesta')} · #{identifier}", STATUSES[receipt['status']], reason)
            if identifier in current_ids:
                self.tree.item(identifier, values=values)
            else:
                self.tree.insert('', 'end', iid=identifier, values=values)
            current_ids.discard(identifier)
        for identifier in current_ids:
            self.tree.delete(identifier)
        if not self.tree.selection() and self.tree.get_children():
            self.tree.selection_set(self.tree.get_children()[0])
        self._detail()
        self.confirm_button.state(['!disabled'] if batch['status'] == 'DRAFT' and counts['eligible_tasks']
                                  else ['disabled'])

    def _detail(self):
        selected = self.tree.selection()
        if not selected or self.batch is None:
            self.explanation.set('Selecciona una propuesta para revisar el cambio y sus fuentes.')
            for widget in (self.before, self.proposed, self.evidence):
                self._write(widget, '')
            return
        item = next(row for row in self.batch['plan']['items'] if str(row['candidate_id']) == selected[0])
        assessment = item.get('assessment') or {}
        from knowledge_orchestrator.ui.dashboard.revision import RISK_LABELS
        risks = ' '.join(RISK_LABELS.get(risk, risk) for risk in assessment.get('risks', []))
        self.explanation.set((assessment.get('rationale') or '; '.join(item['blockers'])) + '\n' + risks)
        self._write(self.before, item.get('before', 'No hay un cambio aplicable en esta revisión.'))
        self._write(self.proposed, item.get('proposed', 'La nota se conserva sin cambios.'))
        evidence = '\n\n'.join(f"{e['source']['title']} · {e['source'].get('source_url', '')}\n{e['quote']}"
                                for e in assessment.get('evidence', []))
        self._write(self.evidence, evidence or 'Sin evidencia aplicable en esta vista previa.')

    def _confirm(self):
        if self._busy or not self.batch or self.batch['status'] != 'DRAFT':
            return
        batch = self.batch
        count = batch['plan']['counts']['eligible_tasks']
        if not count or not messagebox.askyesno('Confirmar revisión',
                f'Se aplicarán {count} propuestas del plan mostrado, conservando el histórico. '
                'Cada una volverá a comprobarse antes de publicar. ¿Confirmar?', parent=self):
            return
        self._submit('batch', lambda: self.service.repository.confirm(batch['batch_id'], owner='ui',
                                                                      plan_hash=batch['plan_hash']))

    def _load_history(self):
        offset = self._offset
        self._submit('history', lambda: self.service.repository.list(owner='ui', offset=offset))

    def _history_page(self, delta):
        if self._busy:
            return
        self._offset = max(0, self._offset + delta)
        self._clear_batch()
        self._load_history()

    def _choose_history(self, _event=None):
        if self._busy:
            return
        batch_id = self._history_ids.get(self.history_choice.get())
        if batch_id:
            self._clear_batch()
            self._submit('batch', lambda: self.service.repository.get(batch_id, owner='ui'))

    def _clear_batch(self):
        self.batch = None
        for identifier in self.tree.get_children():
            self.tree.delete(identifier)
        self._detail()
        self.confirm_button.state(['disabled'])
        self.status.set('Cargando…')

    def _close(self):
        self._closed = True
        if self._poll_id:
            self.after_cancel(self._poll_id)
        self.destroy()
