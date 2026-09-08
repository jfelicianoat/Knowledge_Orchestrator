"""Políticas dentro de Servicios: definir, simular, autorizar y consultar auditoría."""
from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import uuid
from tkinter import messagebox, simpledialog, ttk

from knowledge_orchestrator.ui.automation_form import AutomationForm
from knowledge_orchestrator.ui.automation_plan import AutomationPlanView, text_panel, write_text
from knowledge_orchestrator.ui.automation_presenter import (
    config_summary,
    reasons,
    simulation_matches,
    simulation_selection_matches,
)
from knowledge_orchestrator.ui.review_batch_dialog import STATUSES


class AutomationPanel(ttk.Frame):
    def __init__(self, parent, runtime, colors: dict, ready) -> None:
        super().__init__(parent, padding=12)
        self.runtime, self.service, self.ready = runtime, runtime.automation_governance, ready
        self.policy: dict | None = None
        self.simulation: dict | None = None
        self.review_selection: list[dict] | None = None
        self.control: dict = {}
        self.dirty = self.creating = self.busy = self.control_busy = self.closed = False
        self.policy_offset = self.source_offset = self.audit_offset = 0
        self.simulation_cursor = 0
        self._create_key = uuid.uuid4().hex
        self._simulation_key: str | None = None
        self._audit_selected: tuple[str, ...] = ()
        self._audit_kind_loaded = 'Versiones y decisiones'
        self.policy_rows: list[dict] = []
        self.audit_rows: dict[str, dict] = {}
        self.results: queue.SimpleQueue = queue.SimpleQueue()
        self._next_control_refresh = 0.0
        self._poll_id = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky='ew')
        self.control_text = tk.StringVar(value='Leyendo control global…')
        ttk.Label(bar, textvariable=self.control_text).pack(side='left')
        self.pause_button = ttk.Button(bar, text='Pausar autoaprobación', command=self._pause)
        self.pause_button.pack(side='right', padx=4)
        ttk.Button(bar, text='Actualizar estado', command=self.refresh).pack(side='right', padx=4)
        select = ttk.Frame(self)
        select.grid(row=1, column=0, sticky='ew', pady=10)
        select.columnconfigure(0, weight=1)
        self.choice = ttk.Combobox(select, state='readonly')
        self.choice.grid(row=0, column=0, sticky='ew')
        self.choice.bind('<<ComboboxSelected>>', self._choose)
        self.previous = ttk.Button(select, text='Más recientes', command=lambda: self._policy_page(-100))
        self.previous.grid(row=0, column=1, padx=4)
        self.next = ttk.Button(select, text='Más antiguas', command=lambda: self._policy_page(100))
        self.next.grid(row=0, column=2, padx=4)
        self.new_button = ttk.Button(select, text='Nueva política', command=self._new)
        self.new_button.grid(row=0, column=3, padx=4)
        self.reload_button = ttk.Button(select, text='Recargar política', command=self._reload_policy)
        self.reload_button.grid(row=0, column=4, padx=4)
        self.status = tk.StringVar(value='Selecciona una política o crea una desactivada.')
        ttk.Label(self, textvariable=self.status, wraplength=950, justify='left').grid(row=2, column=0, sticky='ew')
        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=3, column=0, sticky='nsew', pady=8)
        self.form = AutomationForm(self.tabs, colors, self._edited, self._source_page)
        self.plan = AutomationPlanView(self.tabs, colors)
        self.plan.page_size.trace_add('write', self._reset_simulation_key)
        self.audit = ttk.Frame(self.tabs, padding=8)
        for widget, label in ((self.form, 'Condiciones y fuentes'), (self.plan, 'Simulación'),
                               (self.audit, 'Historial')):
            self.tabs.add(widget, text=label)
        self._build_audit(colors)
        actions = ttk.Frame(self)
        actions.grid(row=4, column=0, sticky='ew')
        self.save_button = ttk.Button(actions, text='Guardar desactivada', command=self._save)
        self.simulate_button = ttk.Button(actions, text='Simular guardada', command=self._simulate)
        self.simulate_next = ttk.Button(actions, text='Simular siguientes', command=self._simulate_next)
        self.authorize_button = ttk.Button(actions, text='Autorizar esta versión', style='Accent.TButton',
                                           command=lambda: self._activation(True))
        self.disable_button = ttk.Button(actions, text='Desautorizar', command=lambda: self._activation(False))
        for button in (self.save_button, self.simulate_button, self.simulate_next,
                       self.authorize_button, self.disable_button):
            button.pack(side='left', padx=(0, 8))
        self.form.set_config(None)
        self.bind('<Destroy>', self._destroyed, add='+')
        self._poll_id = self.after(100, self._poll)
        self.refresh()
        self._refresh_control()

    def _build_audit(self, colors):
        self.audit.columnconfigure(0, weight=1)
        self.audit.rowconfigure(2, weight=1)
        bar = ttk.Frame(self.audit)
        bar.grid(row=0, column=0, sticky='ew')
        self.audit_kind = ttk.Combobox(bar, state='readonly', values=(
            'Versiones y decisiones', 'Simulaciones', 'Ejecuciones', 'Pausa global'), width=24)
        self.audit_kind.set('Versiones y decisiones')
        self.audit_kind.pack(side='left')
        self.audit_kind.bind('<<ComboboxSelected>>', lambda _event: self._load_audit(reset=True))
        ttk.Button(bar, text='Consultar', command=self._load_audit).pack(side='left', padx=4)
        self.audit_previous = ttk.Button(bar, text='Más recientes', command=lambda: self._audit_page(-100))
        self.audit_previous.pack(side='right', padx=4)
        self.audit_next = ttk.Button(bar, text='Más antiguos', command=lambda: self._audit_page(100))
        self.audit_next.pack(side='right', padx=4)
        self.audit_tree = ttk.Treeview(self.audit, columns=('date', 'record'), show='headings', height=5,
                                       style='Dark.Treeview', selectmode='browse')
        self.audit_tree.heading('date', text='Fecha')
        self.audit_tree.heading('record', text='Registro')
        self.audit_tree.column('date', width=190)
        self.audit_tree.column('record', width=540)
        self.audit_tree.grid(row=1, column=0, sticky='ew', pady=8)
        self.audit_tree.bind('<<TreeviewSelect>>', self._audit_detail)
        scrollbar = ttk.Scrollbar(self.audit, orient='vertical', command=self.audit_tree.yview)
        scrollbar.grid(row=1, column=1, sticky='ns', pady=8)
        self.audit_tree.configure(yscrollcommand=scrollbar.set)
        frame, self.audit_text = text_panel(self.audit, colors)
        frame.grid(row=2, column=0, sticky='nsew')
        write_text(self.audit_text, 'Selecciona una política y consulta su historial. '
                   'La pausa global tiene historial propio.')

    def _submit(self, kind, operation, *, control=False):
        if self.closed or (self.control_busy if control else self.busy):
            return
        if control:
            self.control_busy = True
        else:
            self.busy = True
        self._actions()
        results = self.results
        def work():
            try:
                results.put((kind, operation(), None, control))
            except Exception as error:
                message = str(error) if isinstance(error, ValueError) else (
                    'No se pudo completar la operación. Actualiza el estado antes de volver a decidir.')
                results.put((kind, None, message, control))
        threading.Thread(target=work, name='automation-governance-ui', daemon=True).start()

    def _poll(self):
        if self.closed:
            return
        try:
            kind, value, error, control = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            if control:
                self.control_busy = False
                self._next_control_refresh = time.monotonic() + 5
            else:
                self.busy = False
            if error:
                self.status.set(error)
                if kind == 'audit':
                    self.audit_kind.set(self._audit_kind_loaded)
            else:
                self._receive(kind, value)
            self._actions()
        self._actions()
        if self.winfo_ismapped() and not self.control_busy and time.monotonic() >= self._next_control_refresh:
            self._refresh_control()
        self._poll_id = self.after(200, self._poll)

    def _receive(self, kind, value):
        if kind == 'control':
            self.control = value
            paused = value['paused']
            self.control_text.set('Autoaprobación pausada · no inicia cambios' if paused else
                                  'Autoaprobación reanudada · solo políticas autorizadas')
            self.pause_button.configure(text='Reanudar políticas autorizadas' if paused else 'Pausar autoaprobación')
        elif kind == 'list':
            offset, source_offset, clear_policy, self.policy_rows, sources = value
            self.policy_offset, self.source_offset = offset, source_offset
            if clear_policy:
                self.policy = self.simulation = None
                self.simulation_cursor = 0
                self._simulation_key = None
                self.dirty = self.creating = False
                self.form.set_config(None)
                self.plan.render(None)
                self._clear_audit()
            self.choice.configure(values=[self._policy_label(row) for row in self.policy_rows])
            if self.policy:
                self.choice.set(self._policy_label({**self.policy, 'name': self.policy['config']['name']}))
            elif self.creating:
                self.choice.set('Nueva política · sin guardar')
            else:
                self.choice.set('Selecciona una política' if self.policy_rows
                                else 'Sin políticas: crea una desactivada')
            self.form.show_sources(sources, self.source_offset)
        elif kind == 'sources':
            self.source_offset, sources = value
            self.form.show_sources(sources, self.source_offset)
        elif kind == 'policy':
            self.policy = value
            self.creating = self.dirty = False
            self.simulation = None
            self.simulation_cursor = 0
            self._simulation_key = None
            self._create_key = uuid.uuid4().hex
            self.form.set_config(value['config'])
            self.plan.render(None)
            self.choice.set(self._policy_label({**value, 'name': value['config']['name']}))
            self.status.set(f"Versión {value['revision']} · " + ('Autorizada' if value['enabled'] else 'Desactivada')
                            + ' · Guardar cambios revoca cualquier autorización anterior.')
            self._clear_audit()
            self.audit_offset = 0
        elif kind in ('simulation', 'historical_simulation'):
            self.simulation = value
            if kind == 'simulation':
                self._simulation_key = None
            self.plan.render(value)
            self.tabs.select(self.plan)
            scope = 'Revisa las propuestas y revisiones que figuran en este registro.'
            if self.review_selection:
                scope = ('El registro corresponde a la propuesta y revisión seleccionadas.'
                         if simulation_selection_matches(value, self.review_selection) else
                         'El registro corresponde a otras propuestas o revisiones. '
                         'Vuelve a simular la propuesta seleccionada antes de autorizar.')
            prefix = 'Simulación histórica. ' if kind == 'historical_simulation' else 'Simulación realizada. '
            self.status.set(prefix + scope + ' Revisa condiciones y evidencia; la simulación no publica cambios.')
        elif kind == 'audit':
            self._audit_kind_loaded, self.audit_offset, rows, more = value
            self.audit_kind.set(self._audit_kind_loaded)
            self._clear_audit()
            for index, row in enumerate(rows):
                identifier = str(index)
                self.audit_rows[identifier] = row
                self.audit_tree.insert('', 'end', iid=identifier, values=(row['created_at'], row['_label']))
            self.audit_previous.state(['!disabled'] if self.audit_offset else ['disabled'])
            self.audit_next.state(['!disabled'] if more else ['disabled'])
            write_text(self.audit_text, 'Selecciona un registro.' if rows else 'No hay registros en esta página.')
        elif kind == 'receipt':
            selected = self.audit_tree.selection()
            current = self.audit_rows.get(selected[0]) if selected else None
            if not current or current.get('run_id') != value['run_id']:
                write_text(self.audit_text, 'Selecciona el registro que quieres consultar.')
                return
            state = STATUSES.get(value['status'], 'Requiere revisión')
            lines = [f"Ejecución de política {value['policy_id']}, versión {value['policy_revision']} · {state}"]
            for item in value['items']:
                result = item['result'] or {}
                lines.append(f"Propuesta {item['candidate_id']} · {STATUSES.get(item['status'], 'Revisión')} · "
                             + (result.get('reason') or reasons(result.get('reasons', []))))
            write_text(self.audit_text, '\n\n'.join(lines))

    @staticmethod
    def _policy_label(row):
        return f"{row['policy_id']} · {row['name']} · v{row['revision']} · " + (
            'Autorizada' if row['enabled'] else 'Desactivada')

    def _actions(self):
        ready = self.ready() and not self.busy
        selected = self.policy is not None
        editing = ready and (selected or self.creating)
        self.form.enable(editing)
        self.simulate_button.configure(text=(f"Simular propuesta {self.review_selection[0]['candidate_id']}"
                                            if self.review_selection else 'Simular guardada'))
        self.simulate_next.configure(text=('Quitar filtro de propuesta' if self.review_selection
                                          else 'Simular siguientes'))
        self.choice.configure(state='readonly' if not self.busy else 'disabled')
        for button, enabled in ((self.new_button, ready), (self.save_button, editing and self.dirty),
                                (self.reload_button, ready and selected),
                                (self.simulate_button, ready and selected and not self.dirty),
                                (self.simulate_next, ready and (self.review_selection is not None or
                                 (selected and not self.dirty and self.simulation is not None
                                 and bool(self.simulation['plan']['items'])
                                 and len(self.simulation['plan']['items']) ==
                                 self.simulation['plan'].get('selection_page', {}).get('limit')))),
                                (self.authorize_button, ready and selected and not self.policy['enabled']
                                 and simulation_matches(self.policy, self.simulation, self.control,
                                                        dirty=self.dirty, selection=self.review_selection)),
                                (self.disable_button, ready and selected and self.policy['enabled'] and not self.dirty),
                                (self.previous, not self.busy and self.policy_offset > 0),
                                (self.next, not self.busy and len(self.policy_rows) == 100),
                                (self.pause_button, self.ready() and bool(self.control) and not self.control_busy)):
            button.state(['!disabled'] if enabled else ['disabled'])
        self.audit_kind.configure(state='disabled' if self.busy else 'readonly')
        self.audit_tree.state(['disabled'] if self.busy else ['!disabled'])

    def _edited(self):
        self.dirty = True
        self.simulation = None
        self._simulation_key = None
        self.simulation_cursor = 0
        self.plan.render(None)
        self.status.set('Cambios sin guardar. Guarda una versión desactivada y vuelve a simular.')
        self._actions()

    def _discard(self):
        return not self.dirty or messagebox.askyesno('Cambios sin guardar', '¿Descartar los cambios del formulario?',
                                                    parent=self)

    def _new(self):
        if self.busy or not self.ready() or not self._discard():
            return
        self.policy = self.simulation = None
        self.simulation_cursor = 0
        self._simulation_key = None
        self.creating = self.dirty = True
        self._create_key = uuid.uuid4().hex
        self.form.set_config(None)
        self.plan.render(None)
        self._clear_audit()
        self.choice.set('Nueva política · sin guardar')
        self.status.set('Selecciona fuentes y condiciones. La política se guardará desactivada.')
        self.tabs.select(self.form)
        self._actions()

    def _choose(self, _event=None):
        index = self.choice.current()
        if self.busy or index < 0 or not self._discard():
            if self.policy:
                self.choice.set(self._policy_label({**self.policy, 'name': self.policy['config']['name']}))
            elif self.creating:
                self.choice.set('Nueva política · sin guardar')
            return
        identifier = self.policy_rows[index]['policy_id']
        if self.policy:
            self.choice.set(self._policy_label({**self.policy, 'name': self.policy['config']['name']}))
        elif self.creating:
            self.choice.set('Nueva política · sin guardar')
        else:
            self.choice.set('Selecciona una política')
        self._submit('policy', lambda: self.service.policies.get(identifier))

    def _reload_policy(self):
        if self.busy or not self.policy or not self._discard():
            return
        identifier = self.policy['policy_id']
        self._submit('policy', lambda: self.service.policies.get(identifier))
        self._refresh_control()

    def refresh(self, *, policy_offset=None, clear_policy=False):
        if self.busy:
            return
        offset = self.policy_offset if policy_offset is None else policy_offset
        source_offset = self.source_offset
        self._submit('list', lambda: (offset, source_offset, clear_policy, self.service.policies.list(offset=offset),
                                     self.runtime.sources.repository.list_sources(offset=source_offset)))
        self._refresh_control()

    def _refresh_control(self):
        self._submit('control', self.service.policies.control, control=True)

    def _policy_page(self, delta):
        if self.busy or not self._discard():
            return
        self.refresh(policy_offset=max(0, self.policy_offset + delta), clear_policy=True)

    def _source_page(self, delta):
        if self.busy:
            return
        self.form._source_selection()
        offset = max(0, self.source_offset + delta)
        self._submit('sources', lambda: (offset, self.runtime.sources.repository.list_sources(offset=offset)))

    def _save(self):
        if self.busy or not self.ready() or not self.dirty:
            return
        try:
            config = self.form.read_config()
        except ValueError as error:
            self.status.set(str(error))
            return
        policy = self.policy
        if policy:
            reason = simpledialog.askstring('Guardar revisión desactivada',
                                             'Motivo del cambio (se revocará la autorización anterior):', parent=self)
            if not reason:
                return
            self._submit('policy', lambda: self.service.policies.update(policy['policy_id'], config,
                expected_revision=policy['revision'], expected_state_revision=policy['state_revision'],
                actor='ui', reason=reason))
        else:
            key = self._create_key
            self._submit('policy', lambda: self.service.policies.create(config, actor='ui', key=key))

    def _simulate(self, *, next_page=False):
        if self.busy or not self.ready() or self.dirty or not self.policy:
            return
        policy = self.policy
        selection = self.review_selection
        if selection:
            self._simulation_key = self._simulation_key or uuid.uuid4().hex
            key = self._simulation_key
            self._submit('simulation', lambda: self.service.simulate(policy['policy_id'],
                expected_revision=policy['revision'], actor='ui', key=key, selection=selection))
            return
        try:
            limit = int(self.plan.page_size.get())
            if not 1 <= limit <= 100:
                raise ValueError
        except ValueError:
            self.status.set('Introduce entre 1 y 100 propuestas por página en la pestaña Simulación.')
            return
        if not next_page:
            if self.simulation_cursor != 0:
                self._simulation_key = None
            self.simulation_cursor = 0
        cursor = self.simulation_cursor
        if self._simulation_key is None:
            self._simulation_key = uuid.uuid4().hex
        key = self._simulation_key
        self._submit('simulation', lambda: self.service.simulate_page(policy['policy_id'],
                     expected_revision=policy['revision'], actor='ui', key=key,
                     after_candidate_id=cursor, limit=limit))

    def _reset_simulation_key(self, *_args):
        self._simulation_key = None

    def _simulate_next(self):
        if self.busy:
            return
        if self.review_selection:
            self.review_selection = self.simulation = None
            self.simulation_cursor = 0
            self._simulation_key = None
            self.plan.render(None)
            self.status.set('Filtro retirado. La próxima simulación usará el ámbito completo de la política.')
            self._actions()
            return
        if self.dirty or not self.simulation:
            return
        items = self.simulation['plan']['items']
        if items:
            cursor = max(item['candidate_id'] for item in items)
            if cursor != self.simulation_cursor:
                self._simulation_key = None
            self.simulation_cursor = cursor
            self._simulate(next_page=True)

    def review_candidate(self, candidate_id: int, revision: int) -> bool:
        if self.busy or not self.ready():
            return False
        self.review_selection = [{'candidate_id': candidate_id, 'expected_revision': revision}]
        self.simulation = None
        self.simulation_cursor = 0
        self._simulation_key = None
        self.plan.render(None)
        self.status.set(f'Propuesta {candidate_id} · revisión {revision}. Elige una política, revisa sus condiciones '
                        'y pulsa «Simular propuesta». La simulación no publica cambios.')
        self._actions()
        return True

    def _activation(self, enabled: bool):
        policy, simulation = self.policy, self.simulation
        if self.busy or not self.ready() or self.dirty or not policy:
            return
        if enabled and not simulation_matches(policy, simulation, self.control,
                                              dirty=self.dirty, selection=self.review_selection):
            return
        title = 'Autorizar esta versión' if enabled else 'Desautorizar política'
        description = config_summary(policy['config']) + ('\n\nSe permitirán futuras propuestas que cumplan estas '
            'condiciones mientras el control global esté reanudado. ¿Autorizar?' if enabled else '\n\n¿Desautorizar?')
        if not messagebox.askyesno(title, description, parent=self):
            return
        reason = simpledialog.askstring(title, 'Motivo de la decisión:', parent=self)
        if not reason:
            return
        identifier = simulation['simulation_id'] if enabled and simulation else None
        self._submit('policy', lambda: self.service.set_enabled(policy['policy_id'], enabled,
            expected_revision=policy['revision'], expected_state_revision=policy['state_revision'], actor='ui',
            reason=reason, reviewed_simulation_id=identifier))

    def _pause(self):
        if not self.ready() or self.control_busy or not self.control:
            return
        paused, revision = not self.control['paused'], self.control['revision']
        title = 'Pausar autoaprobación' if paused else 'Reanudar políticas autorizadas'
        message = ('La pausa impide nuevos cambios. Los ya iniciados pueden terminar o recuperarse. ¿Pausar?' if paused
                   else 'Las políticas autorizadas podrán aplicar futuras propuestas elegibles. ¿Reanudar?')
        if not messagebox.askyesno(title, message, parent=self):
            return
        reason = simpledialog.askstring(title, 'Motivo de la decisión:', parent=self)
        if reason:
            self._submit('control', lambda: self.service.policies.set_paused(
                paused, expected_revision=revision, actor='ui', reason=reason), control=True)

    def _clear_audit(self):
        self.audit_rows = {}
        self._audit_selected = ()
        self.audit_tree.delete(*self.audit_tree.get_children())
        write_text(self.audit_text, 'Consulta el historial y selecciona un registro.')
        self.audit_previous.state(['disabled'])
        self.audit_next.state(['disabled'])

    def _load_audit(self, *, reset=False, offset=None):
        if self.busy:
            return
        kind, policy = self.audit_kind.get(), self.policy
        if not policy and kind != 'Pausa global':
            self.status.set('Selecciona una política para consultar este historial.')
            return
        if reset:
            offset = 0
        offset = self.audit_offset if offset is None else offset
        repository = self.service.repository
        def read():
            if kind == 'Pausa global':
                rows = repository.control_history(offset=offset)
                return [{**r, '_label': 'Pausa' if r['paused'] else 'Reanudación'} for r in rows], len(rows) == 100
            assert policy is not None
            if kind == 'Versiones y decisiones':
                history = repository.history(policy['policy_id'], offset=offset)
                versions = [{**r, '_label': f"Configuración · v{r['revision']}"} for r in history['versions']]
                decisions = [{**r, '_label': ('Autorización' if r['enabled'] else 'Desactivación')
                              + f" · v{r['revision']}"}
                             for r in history['decisions']]
                return versions + decisions, max(len(versions), len(decisions)) == 100
            record_kind = 'simulations' if kind == 'Simulaciones' else 'runs'
            rows = repository.list_records(record_kind, policy_id=policy['policy_id'], offset=offset)
            return [{**r, '_label': f"Versión {r['policy_revision']} · "
                     + STATUSES.get(r.get('status'), 'Simulación sin publicación')}
                    for r in rows], len(rows) == 100
        self._submit('audit', lambda: (kind, offset, *read()))

    def _audit_page(self, delta):
        if not self.busy:
            self._load_audit(offset=max(0, self.audit_offset + delta))

    def _audit_detail(self, _event=None):
        selected = self.audit_tree.selection()
        if self.busy:
            if selected != self._audit_selected and all(self.audit_tree.exists(i) for i in self._audit_selected):
                self.audit_tree.selection_set(self._audit_selected)
            return
        row = self.audit_rows.get(selected[0]) if selected else None
        if not row:
            return
        self._audit_selected = selected
        write_text(self.audit_text, 'Leyendo registro…')
        if 'run_id' in row:
            self._submit('receipt', lambda: self.runtime.automation_execution.repository.get(row['run_id']))
        elif 'simulation_id' in row:
            self._submit('historical_simulation', lambda: self.service.policies.simulation(row['simulation_id']))
        else:
            details = f"{row['_label']} · {row['created_at']}\n{row['actor']}\n\n{row['reason']}"
            if 'config' in row:
                details += '\n\n' + config_summary(row['config'])
            if row.get('reviewed_simulation_id'):
                details += '\n\nLa decisión conserva la simulación revisada en el historial de simulaciones.'
            write_text(self.audit_text, details)

    def _destroyed(self, event):
        if event.widget == self:
            self.closed = True
            if self._poll_id:
                self.after_cancel(self._poll_id)
