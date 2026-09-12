"""THESIS: revisar una compensación concreta antes de restaurar conocimiento.
OWN-WORLD: grafito/cian y Segoe UI heredados de Revisión, sin otra identidad visual.
STORY: elegir publicación, comparar el plan, confirmar con motivo, consultar recibo.
FIRST VIEWPORT: publicaciones arriba, antes/propuesto en paralelo y decisión al pie.
FORM: extensión del maestro-detalle existente; selección estable e I/O fuera de Tk.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
import uuid
from tkinter import messagebox, simpledialog, ttk

from knowledge_orchestrator.integrations.obsidian_bridge import ObsidianBridgeUnavailable
from knowledge_orchestrator.services.reversion_view import reversion_view
from knowledge_orchestrator.ui.automation_plan import text_panel
from knowledge_orchestrator.ui.review_batch_dialog import ReviewBatchDialog

STATES = {'PREVIEW': 'Vista previa · sin modificar notas', 'APPLYING': 'Reversión iniciada',
          'APPLIED': 'Reversión aplicada · histórico conservado', 'CONFLICT': 'Conflicto · requiere revisión'}
KNOWLEDGE_STATES = {'CURRENT': 'Vigente', 'DISPUTED': 'En disputa', 'UNCERTAIN': 'Incierto',
                    'REVIEW_REQUIRED': 'Requiere revisión'}


class ReversionPanel(ttk.Frame):
    def __init__(self, parent, service, colors, ready) -> None:
        super().__init__(parent, padding=12)
        self.service, self.ready = service, ready
        self.busy = self.closed = self.uncertain = False
        self.offset = self.history_offset = 0
        self.application: dict | None = None
        self.record: dict | None = None
        self.rows: dict[str, dict] = {}
        self.history_rows: list[dict] = []
        self._preview_key: str | None = None
        self.results: queue.SimpleQueue = queue.SimpleQueue()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=colors['surface'], highlightthickness=0, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        outer_scroll = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        outer_scroll.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=outer_scroll.set)
        body = ttk.Frame(self.canvas)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(4, weight=1, minsize=220)
        window = self.canvas.create_window((0, 0), anchor='nw', window=body)
        body.bind('<Configure>', lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(
            window, width=event.width, height=max(body.winfo_reqheight(), event.height)))
        self.status = tk.StringVar(value='Selecciona una publicación para preparar su reversión '
                                        'o consultar sus recibos.')
        ttk.Label(body, textvariable=self.status, wraplength=1000, justify='left').grid(row=0, column=0, sticky='ew')
        bar = ttk.Frame(body)
        bar.grid(row=1, column=0, sticky='ew', pady=8)
        self.refresh_button = ttk.Button(bar, text='Actualizar publicaciones', command=self._load)
        self.refresh_button.pack(side='left')
        self.previous = ttk.Button(bar, text='Más recientes', command=lambda: self._page(-100))
        self.previous.pack(side='right', padx=4)
        self.next = ttk.Button(bar, text='Más antiguas', command=lambda: self._page(100))
        self.next.pack(side='right', padx=4)
        self.tree = ttk.Treeview(body, columns=('note', 'date', 'actor', 'state'), show='headings',
                                 height=4, selectmode='browse', style='Dark.Treeview')
        for key, title, width in (('note', 'Publicación / nota', 320), ('date', 'Aplicada', 175),
                                   ('actor', 'Decisión original', 170), ('state', 'Reversión', 240)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=70)
        self.tree.grid(row=2, column=0, sticky='ew')
        scroll = ttk.Scrollbar(body, orient='vertical', command=self.tree.yview)
        scroll.grid(row=2, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>', self._select)
        history = ttk.Frame(body)
        history.grid(row=3, column=0, sticky='ew', pady=8)
        history.columnconfigure(1, weight=1)
        ttk.Label(history, text='Vistas previas y decisiones').grid(row=0, column=0, padx=(0, 8))
        self.history_choice = ttk.Combobox(history, state='readonly')
        self.history_choice.grid(row=0, column=1, sticky='ew')
        self.history_choice.bind('<<ComboboxSelected>>', self._choose_history)
        self.history_refresh = ttk.Button(history, text='Consultar', command=self._load_history)
        self.history_refresh.grid(row=0, column=2, padx=4)
        self.history_previous = ttk.Button(history, text='Más recientes', command=lambda: self._history_page(-100))
        self.history_previous.grid(row=0, column=3, padx=4)
        self.history_next = ttk.Button(history, text='Más antiguas', command=lambda: self._history_page(100))
        self.history_next.grid(row=0, column=4)
        panes = ttk.Panedwindow(body, orient='horizontal')
        panes.grid(row=4, column=0, sticky='nsew')
        widgets = []
        for title in ('Antes de la reversión', 'Resultado de la reversión'):
            outer = ttk.Frame(panes)
            outer.columnconfigure(0, weight=1)
            outer.rowconfigure(1, weight=1)
            ttk.Label(outer, text=title).grid(row=0, column=0, sticky='w', pady=4)
            frame, widget = text_panel(outer, colors)
            frame.grid(row=1, column=0, sticky='nsew')
            panes.add(outer, weight=1)
            widgets.append(widget)
        self.before, self.proposed = widgets
        frame, self.evidence = text_panel(body, colors, height=4)
        frame.grid(row=5, column=0, sticky='ew', pady=8)
        actions = ttk.Frame(self)
        actions.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        self.prepare_button = ttk.Button(actions, text='Preparar nueva vista previa', command=self._prepare)
        self.prepare_button.pack(side='left', padx=(0, 8))
        self.reload_button = ttk.Button(actions, text='Actualizar recibo', command=self._reload)
        self.reload_button.pack(side='left')
        self.confirm_button = ttk.Button(actions, text='Confirmar reversión', style='Accent.TButton',
                                          command=self._confirm)
        self.confirm_button.pack(side='right')
        self._bind_scroll(body)
        self._clear_record()
        self.bind('<Destroy>', self._destroyed, add='+')
        self._poll_id = self.after(100, self._poll)
        self._load()

    def _bind_scroll(self, widget):
        if not isinstance(widget, (tk.Text, ttk.Treeview, ttk.Combobox, ttk.Scrollbar)):
            widget.bind('<MouseWheel>', lambda event: self.canvas.yview_scroll(
                -1 if event.delta > 0 else 1, 'units'), add='+')
        widget.bind('<FocusIn>', self._reveal_focus, add='+')
        for child in widget.winfo_children():
            self._bind_scroll(child)

    def _reveal_focus(self, event):
        y = event.widget.winfo_rooty() - self.canvas.winfo_rooty()
        height = event.widget.winfo_height()
        viewport = self.canvas.winfo_height()
        delta = y if y < 0 or height > viewport else max(0, y + height - viewport)
        bounds = self.canvas.bbox('all')
        if delta and bounds and bounds[3] > bounds[1]:
            position = self.canvas.canvasy(0) + delta - bounds[1]
            self.canvas.yview_moveto(max(0, position / (bounds[3] - bounds[1])))

    def _submit(self, kind, operation):
        if self.busy or self.closed:
            return
        self.busy = True
        if kind == 'record' and self.record:
            self.uncertain = True
        self._actions()
        results = self.results
        def work():
            try:
                results.put((kind, operation(), None))
            except Exception as error:
                if isinstance(error, ObsidianBridgeUnavailable):
                    message = ('Reversión pendiente. Abre y comprueba el puente de Obsidian, '
                               'y reinicia el Orchestrator para recuperarla.')
                else:
                    message = str(error) if isinstance(error, ValueError) else 'No se pudo completar la operación.'
                results.put((kind, None, message))
        threading.Thread(target=work, name='reversion-review-ui', daemon=True).start()

    def _poll(self):
        if self.closed:
            return
        try:
            kind, value, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            if error:
                self.uncertain = self.uncertain or kind == 'confirmed'
                self.status.set(error.rstrip('. ') + '.' + (' Pulsa «Actualizar recibo» antes de volver a decidir.'
                                         if self.uncertain else ' Actualiza o prepara una nueva revisión.'))
            else:
                self._receive(kind, value)
        self._actions()
        self._poll_id = self.after(200, self._poll)

    def _receive(self, kind, value):
        if kind == 'publications':
            self.offset, value = value
            selected = str(self.application['candidate_id']) if self.application else None
            self.rows = {str(row['candidate_id']): row for row in value}
            self.tree.delete(*self.tree.get_children())
            for identifier, row in self.rows.items():
                self.tree.insert('', 'end', iid=identifier, values=(f"{row['title']} · {identifier}",
                    row['applied_at'], self._actor_label(row['reviewed_by']),
                    STATES.get(row['reversion_status'], 'Sin reversión aplicada')))
            if selected in self.rows:
                self.application = self.rows[selected]
                self.tree.selection_set(selected)
            else:
                self.application = None
                self._clear_record()
                self._clear_history()
                self.status.set('Selecciona una publicación.' if value
                                else 'No hay publicaciones aplicadas en esta página.')
        elif kind == 'history':
            candidate_id, offset, rows = value
            if not self.application or self.application['candidate_id'] != candidate_id:
                return
            self.history_offset = offset
            self.history_rows = rows
            self.history_choice.configure(values=[self._history_label(row) for row in rows])
            self.history_choice.set(self._history_label(self.record) if self.record else
                                    ('Selecciona un registro' if rows else 'Sin vistas previas ni decisiones'))
        elif kind in ('record', 'confirmed'):
            if not self.application or self.application['candidate_id'] != value['candidate_id']:
                return
            self.record = value
            self.uncertain = False
            self._preview_key = None
            self.history_choice.set(self._history_label(value))
            plan = value['plan']
            ReviewBatchDialog._write(self.before, plan['before'])
            ReviewBatchDialog._write(self.proposed, plan['proposed'])
            state = KNOWLEDGE_STATES[plan['restore_state']]
            detail = (f"Se restablece la afirmación {plan['target_claim_id']} como «{state}» en un nuevo período. "
                      f"La afirmación {plan['successor_claim_id']} pasa a histórico. "
                      'Se conservan las revisiones y la publicación original. Restaurar no verifica un hecho.\n\n')
            detail += '\n\n'.join(f"Documento de origen {e['source_note_id']} · "
                                    f"afirmación {e['claim_id']}\n{e['quote']}"
                                    for e in plan['evidence'])
            if value['reason']:
                detail += '\n\nMotivo registrado: ' + value['reason']
            ReviewBatchDialog._write(self.evidence, detail)
            self.status.set(STATES[value['status']] + (' · Si quedó interrumpida, se recupera al reiniciar.'
                            if value['status'] == 'APPLYING' else '')
                            + (' · Plan de otro consumidor: solo consulta.'
                               if value['owner'] != 'ui' and value['status'] == 'PREVIEW' else ''))
            if kind == 'confirmed':
                self._load()

    @staticmethod
    def _history_label(row):
        return (f"{row['created_at']} · {STATES[row['status']]} · "
                + ReversionPanel._actor_label(row['owner']) + f" · {row['reversion_id'][:8]}")

    @staticmethod
    def _actor_label(actor):
        if actor == 'ui':
            return 'Desde esta aplicación'
        if actor and actor.startswith('api:'):
            return 'Consumidor ' + actor[4:]
        if actor and actor.startswith('policy:'):
            return actor.replace('policy:', 'Política ').replace(':revision:', ' · versión ')
        return actor or 'Revisión anterior'

    def _actions(self):
        available = not self.busy
        selected = self.application is not None
        editable = available and self.ready()
        self.tree.state(['!disabled'] if available else ['disabled'])
        self.history_choice.configure(state='readonly' if available else 'disabled')
        for button, enabled in ((self.refresh_button, available), (self.previous, available and self.offset > 0),
            (self.next, available and len(self.rows) == 100),
            (self.prepare_button, editable and selected and self.application['reversion_status'] is None),
            (self.reload_button, available and self.record is not None),
            (self.confirm_button, editable and selected and self.record is not None
             and self.record['candidate_id'] == self.application['candidate_id'] and self.record['owner'] == 'ui'
             and self.record['status'] == 'PREVIEW'
             and not self.uncertain), (self.history_refresh, available and selected),
            (self.history_previous, available and selected and self.history_offset > 0),
            (self.history_next, available and selected and len(self.history_rows) == 100)):
            button.state(['!disabled'] if enabled else ['disabled'])

    def _clear_record(self):
        self.record = None
        self.uncertain = False
        self._preview_key = None
        for widget in (self.before, self.proposed, self.evidence):
            ReviewBatchDialog._write(widget, 'Selecciona una publicación y prepara o consulta su vista previa.')

    def _clear_history(self):
        self.history_offset = 0
        self.history_rows = []
        self.history_choice.configure(values=[])
        self.history_choice.set('Selecciona una publicación')

    def _select(self, _event=None):
        selected = self.tree.selection()
        previous = (str(self.application['candidate_id']),) if self.application else ()
        if self.busy:
            if selected != previous:
                self.tree.selection_set(previous)
            return
        if selected == previous:
            return
        self.application = self.rows.get(selected[0]) if selected else None
        self._clear_record()
        self._clear_history()
        if self.application:
            self.status.set('Prepara una vista previa o consulta una decisión anterior de esta publicación.')
            self._load_history()
        self._actions()

    def _load(self, offset=None):
        offset = self.offset if offset is None else offset
        self._submit('publications', lambda: (offset, self.service.repository.publications(offset=offset)))

    def _page(self, delta):
        if not self.busy:
            self._load(max(0, self.offset + delta))

    def _load_history(self, offset=None):
        if self.busy or not self.application:
            return
        identifier = self.application['candidate_id']
        offset = self.history_offset if offset is None else offset
        self._submit('history', lambda: (identifier, offset, self.service.repository.list_records(
            actor=None, candidate_id=identifier, offset=offset)))

    def _history_page(self, delta):
        if not self.busy:
            self._load_history(max(0, self.history_offset + delta))

    def _choose_history(self, _event=None):
        index = self.history_choice.current()
        if self.busy or index < 0:
            if self.record:
                self.history_choice.set(self._history_label(self.record))
            return
        self._read_record(self.history_rows[index]['reversion_id'])

    def _read_record(self, identifier):
        self._submit('record', lambda: reversion_view(self.service.repository.audit(identifier)))

    def _reload(self):
        if self.record:
            self._read_record(self.record['reversion_id'])

    def _prepare(self):
        if self.busy or not self.ready() or not self.application or self.application['reversion_status']:
            return
        item = self.application
        self._preview_key = self._preview_key or uuid.uuid4().hex
        key = self._preview_key
        self._submit('record', lambda: reversion_view(self.service.preview(item['candidate_id'],
            expected_revision=item['proposal_revision'], actor='ui', key=key)))

    def _confirm(self):
        if self.busy or not self.ready() or self.uncertain or not self.record or not self.application \
                or self.record['candidate_id'] != self.application['candidate_id'] \
                or self.record['owner'] != 'ui' or self.record['status'] != 'PREVIEW':
            return
        record = self.record
        if not messagebox.askyesno('Confirmar reversión',
            'Se restaurará la nota mostrada y se registrará un nuevo período del conocimiento anterior. '
            'Se conservarán ambas revisiones y el recibo original. ¿Confirmar el cambio revisado?', parent=self):
            return
        reason = simpledialog.askstring('Motivo de reversión', 'Explica por qué has decidido restaurar esta revisión:',
                                         parent=self)
        if not reason:
            return
        self._submit('confirmed', lambda: reversion_view(self.service.confirm(record['reversion_id'], actor='ui',
            expected_plan_hash=record['plan_hash'], reason=reason)))

    def _destroyed(self, event):
        if event.widget == self:
            self.closed = True
            self.after_cancel(self._poll_id)
