"""API y procesos automáticos observados, integrados en la navegación de operaciones."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk

from knowledge_orchestrator.services.operations_status import OperationsStatusService
from knowledge_orchestrator.ui.automation_panel import AutomationPanel
from knowledge_orchestrator.ui.dashboard.operaciones import OperacionesMixin
from knowledge_orchestrator.ui.review_batch_dialog import ReviewBatchDialog

API_STATES = {'STOPPED': 'Detenida', 'RUNNING': 'Escuchando en este equipo', 'STOPPING': 'Cerrando', 'ERROR': 'Error'}
API_ERRORS = {'API_CREDENTIALS_NOT_CONFIGURED': 'No hay consumidores con credenciales válidas.',
              'API_BIND_FAILED': 'El puerto está ocupado o restringido.',
              'API_START_FAILED': 'No se pudo iniciar el servidor.', 'API_SERVER_FAILED': 'El servidor se interrumpió.',
              'API_SERVER_STOPPED_UNEXPECTEDLY': 'El servidor dejó de atender solicitudes.',
              'API_STOP_PENDING': 'El cierre sigue pendiente.'}
PERMISSIONS = {'read': 'Lectura', 'query': 'Consultas IA', 'ingest': 'Ingesta',
               'sources': 'Fuentes', 'review': 'Revisión', 'governance': 'Gobernanza'}


class ServiciosMixin(OperacionesMixin):
    def _show_page(self, page: str) -> None:
        super()._show_page(page)
        if page == 'services':
            self._refresh_services()

    def _build_services(self) -> None:
        self._services_status = OperationsStatusService(self.runtime)
        self._services_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._services_busy = False
        self._services_snapshot: dict = {}
        self._api_activity: list[dict] = []
        self._api_activity_offset = 0
        page = self._new_page('services')
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self._page_heading(page, 'API y automatizaciones',
                           'Consulta quién utiliza el conocimiento y qué procesos están trabajando.')
        notebook = ttk.Notebook(page)
        self._services_tabs = notebook
        notebook.grid(row=1, column=0, sticky='nsew', padx=24, pady=(0, 20))
        api, automation = ttk.Frame(notebook), ttk.Frame(notebook)
        self._services_automation_page = automation
        notebook.add(api, text='API y consumidores')
        notebook.add(automation, text='Automatizaciones')
        self._build_api_status(api)
        self._build_automation_status(automation)

    def _build_api_status(self, page):
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)
        self.api_status_var = tk.StringVar(value='Leyendo estado de esta sesión…')
        ttk.Label(page, textvariable=self.api_status_var, wraplength=940, justify='left').grid(
            row=0, column=0, sticky='ew', padx=16, pady=12)
        actions = ttk.Frame(page)
        actions.grid(row=1, column=0, sticky='ew', padx=12)
        ttk.Label(actions, text='Puerto local').pack(side='left', padx=4)
        self.api_port_var = tk.StringVar(value='8766')
        self.api_port_entry = ttk.Entry(actions, textvariable=self.api_port_var, width=7)
        self.api_port_entry.pack(side='left', padx=4)
        self.api_start_button = ttk.Button(actions, text='Iniciar API', command=lambda: self._change_api(True))
        self.api_start_button.pack(side='left', padx=4)
        self.api_stop_button = ttk.Button(actions, text='Detener API', command=lambda: self._change_api(False))
        self.api_stop_button.pack(side='left', padx=4)
        self.api_copy_button = ttk.Button(actions, text='Copiar dirección', command=self._copy_api_address)
        self.api_copy_button.pack(side='left', padx=4)
        ttk.Button(actions, text='Actualizar estado', command=self._refresh_services).pack(side='right', padx=4)
        self.api_hint_var = tk.StringVar(value='')
        ttk.Label(page, textvariable=self.api_hint_var, wraplength=940, justify='left').grid(
            row=2, column=0, sticky='ew', padx=16, pady=8)
        panes = ttk.Panedwindow(page, orient='vertical')
        panes.grid(row=3, column=0, sticky='nsew', padx=16)
        clients, activity = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(clients, weight=1)
        panes.add(activity, weight=2)
        self.api_consumers_tree = self._service_tree(clients, [
            ('name', 'Consumidor', 180), ('scopes', 'Permisos configurados', 250),
            ('requests', 'Solicitudes', 90), ('errors', 'Errores', 75), ('seen', 'Última actividad', 200)])
        self.api_activity_tree = self._service_tree(activity, [
            ('client', 'Consumidor', 150), ('operation', 'Operación', 330),
            ('result', 'Resultado', 100), ('date', 'Fecha', 200)])
        pager = ttk.Frame(page)
        pager.grid(row=4, column=0, sticky='ew', padx=16, pady=8)
        self.api_activity_caption = tk.StringVar(value='Sin solicitudes registradas.')
        ttk.Label(pager, textvariable=self.api_activity_caption).pack(side='left')
        self.api_activity_previous = ttk.Button(pager, text='Anteriores', command=lambda: self._page_api_activity(-100))
        self.api_activity_previous.pack(side='right', padx=4)
        self.api_activity_next = ttk.Button(pager, text='Siguientes', command=lambda: self._page_api_activity(100))
        self.api_activity_next.pack(side='right', padx=4)

    @staticmethod
    def _service_tree(parent, columns):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        tree = ttk.Treeview(parent, columns=[column[0] for column in columns], show='headings',
                            style='Dark.Treeview', height=5, selectmode='browse')
        for key, title, width in columns:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=60)
        tree.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(parent, orient='vertical', command=tree.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        tree.configure(yscrollcommand=scroll.set)
        return tree

    def _build_automation_status(self, page):
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        notebook = ttk.Notebook(page)
        self._automation_tabs = notebook
        notebook.grid(row=0, column=0, sticky='nsew')
        overview = ttk.Frame(notebook)
        self.automation_panel = AutomationPanel(notebook, self.runtime, self.colors, self._governance_ready)
        notebook.add(overview, text='Procesos y estado')
        notebook.add(self.automation_panel, text='Políticas y decisiones')
        self._build_automation_summary(overview)

    def _review_proposal_policy(self, candidate_id: int, revision: int):
        if not self.automation_panel.review_candidate(candidate_id, revision):
            self.status_var.set('Espera a que termine la operación de políticas y vuelve a abrir la evaluación.')
            return
        self._show_page('services')
        self._services_tabs.select(self._services_automation_page)
        self._automation_tabs.select(self.automation_panel)

    def _governance_ready(self):
        startup = getattr(self, '_startup', None)
        return bool(startup and startup.done and startup.error is None)

    def _build_automation_summary(self, page):
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        self.automation_detail = tk.Text(page, wrap='word', bg=self.colors['raised'], fg=self.colors['text'],
                                         padx=18, pady=16, relief='flat', state='disabled', height=12)
        self.automation_detail.grid(row=0, column=0, sticky='nsew', padx=(16, 30), pady=12)
        scroll = ttk.Scrollbar(page, orient='vertical', command=self.automation_detail.yview)
        scroll.grid(row=0, column=0, sticky='nse', padx=(0, 16), pady=12)
        self.automation_detail.configure(yscrollcommand=scroll.set)
        actions = ttk.Frame(page)
        actions.grid(row=1, column=0, sticky='ew', padx=12, pady=(0, 12))
        for label, action in [
            ('Ver fuentes y frecuencia', lambda: self._show_page('sources')),
            ('Ver análisis pendientes', lambda: self._open_flow('analysis', scope='pending')),
            ('Ver lotes confirmados', lambda: ReviewBatchDialog(self, self.runtime.review_batches, history=True)),
        ]:
            ttk.Button(actions, text=label, command=action).pack(side='left', padx=4)

    def _change_api(self, start: bool) -> None:
        if not self._startup.done or self._startup.error is not None:
            self.status_var.set('Espera a que termine el arranque del servicio.')
            return
        try:
            port = int(self.api_port_var.get()) if start else 8766
            if start and not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.status_var.set('Introduce un puerto entre 1 y 65535.')
            return
        operation = (lambda: self.runtime.api_server.start(port=port)) if start else self.runtime.api_server.stop
        self._read_services(operation)

    def _copy_api_address(self):
        address = self._services_snapshot.get('api', {}).get('address')
        if address:
            self.clipboard_clear()
            self.clipboard_append(address)
            self.status_var.set('Dirección local copiada; cada consumidor necesita su propia credencial.')

    def _refresh_services(self):
        self._read_services()

    def _read_services(self, operation=None):
        if self._services_busy:
            return
        self._services_busy = True
        self.api_start_button.state(['disabled'])
        self.api_stop_button.state(['disabled'])
        results, service = self._services_queue, self._services_status

        def read():
            error = None
            try:
                if operation:
                    operation()
            except Exception as problem:
                error = str(problem) if isinstance(problem, ValueError) else 'No se pudo cambiar el servicio API.'
            try:
                results.put((service.snapshot(), error))
            except Exception:
                results.put((None, error or 'No se pudo consultar el estado de los servicios.'))

        threading.Thread(target=read, name='services-status', daemon=True).start()
        self.after(100, self._poll_services)

    def _poll_services(self):
        try:
            snapshot, error = self._services_queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_services)
            return
        self._services_busy = False
        if snapshot is not None:
            self._services_snapshot = snapshot
            self._render_services(snapshot)
        if error:
            self.api_hint_var.set(error)
            self.status_var.set(error)

    def _render_services(self, snapshot):
        api = snapshot['api']
        state = API_STATES[api['state']]
        self.api_status_var.set(f"{state} · {api['address'] or 'Sin listener activo en esta sesión'}\n"
                                'La API solo acepta conexiones locales autenticadas. '
                                'Esta vista no comprueba otros procesos.')
        self.api_hint_var.set(API_ERRORS.get(api['error_code'], '') or (
            'Consumidores cargados para este servidor.' if api['running'] else
            'Acceso configurado. Inicia la API para atender solicitudes.' if api['configured'] else
            'No hay acceso configurado. Los consumidores y credenciales se cargan desde KO_API_CLIENTS al iniciar.'))
        ready = self._startup.done and self._startup.error is None
        self.api_start_button.state(['!disabled'] if ready and api['configured'] and not api['running']
                                    and api['state'] != 'STOPPING' else ['disabled'])
        self.api_stop_button.state(['!disabled'] if api['running'] else ['disabled'])
        self.api_copy_button.state(['!disabled'] if api['running'] else ['disabled'])
        self.api_port_entry.state(['disabled'] if api['running'] else ['!disabled'])
        consumers = [(client['name'], (
            client['name'], ', '.join(PERMISSIONS[scope] for scope in client['scopes'])
            if client['configured'] else 'Acceso no configurado en esta sesión', client['requests'],
            client['errors'], client['last_seen'] or 'Sin actividad')) for client in snapshot['consumers']]
        self._replace_tree(self.api_consumers_tree, consumers)
        for index, (identifier, _) in enumerate(consumers):
            self.api_consumers_tree.move(identifier, '', index)
        self._api_activity = snapshot['activity']
        self._render_api_activity()
        sources, batches, analysis, workers = (snapshot[key] for key in ('sources', 'batches', 'analysis', 'workers'))
        governance = snapshot['autoapproval']
        def worker_label(key):
            return 'Activo' if workers[key] else 'Detenido'

        details = (
            f"Vigilancia de fuentes · {worker_label('sources')}\n"
            f"{sources['enabled']} fuentes activas · {sources['checking']} comprobaciones en curso · "
            f"{sources['errors']} fuentes con incidencias.\n"
            'Cada fuente conserva su frecuencia y su decisión de incorporar o revisar novedades.\n\n'
            f"Análisis de conocimiento · {worker_label('broker')}\n"
            f"{sum(analysis.get(s, 0) for s in ('READY', 'SUBMITTING', 'QUEUED', 'PROCESSING'))} pendientes · "
            f"{analysis.get('ERROR', 0)} con error. La disponibilidad del Broker se muestra en la cabecera.\n\n"
            f"Lotes confirmados por personas · {worker_label('reviews')}\n"
            f"{batches.get('READY', 0)} en cola · {batches.get('RUNNING', 0)} aplicando · "
            f"{batches.get('RECOVERY_REQUIRED', 0)} pendientes de recuperar al reiniciar.\n"
            'Solo se ejecutan las propuestas del plan que confirmó una persona.\n\n'
            f"Autoaprobación por políticas · {'Activa' if governance['enabled'] else 'Desactivada'}\n"
            f"Planificador · {worker_label('automations')} · "
            f"{governance['schedules']['evaluating']} evaluaciones en curso · "
            f"{governance['schedules']['errors']} políticas con incidencias.\n"
            f"{governance['policies']['total']} políticas registradas · "
            f"{governance['policies']['enabled']} autorizadas. "
            f"Control global: {'pausado' if governance['control']['paused'] else 'reanudado'}.\n"
            f"Intentos contabilizados hoy (UTC): {governance['reserved_today']}. "
            f"Ejecuciones pendientes de recuperar: {governance['runs'].get('RECOVERY_REQUIRED', 0)}.\n"
            'La pausa impide iniciar nuevas aplicaciones; las ya iniciadas se completan o recuperan. '
            'En «Políticas y decisiones» puedes configurar fuentes, simular, autorizar y consultar el historial. '
            'La confianza de un modelo o una fuente no autoriza por sí sola cambios en las notas.'
        )
        if self.automation_detail.get('1.0', 'end-1c') != details:
            self.automation_detail.configure(state='normal')
            self.automation_detail.delete('1.0', 'end')
            self.automation_detail.insert('1.0', details)
            self.automation_detail.configure(state='disabled')

    def _page_api_activity(self, delta):
        self._api_activity_offset = max(0, self._api_activity_offset + delta)
        self._render_api_activity()

    def _render_api_activity(self):
        total = len(self._api_activity)
        self._api_activity_offset = min(self._api_activity_offset, max(0, ((total - 1) // 100) * 100))
        start = self._api_activity_offset
        rows = self._api_activity[start:start + 100]
        activity = [(str(row['event_id']), (
            row['client'] or 'Sin autenticación', f"{row['method']} {row['route']}", row['status'] or '—',
            row['created_at'])) for row in rows]
        self._replace_tree(self.api_activity_tree, activity)
        for index, (identifier, _) in enumerate(activity):
            self.api_activity_tree.move(identifier, '', index)
        self.api_activity_caption.set(f'Actividad {start + 1}–{start + len(rows)} de {total} · '
                                      'Recuentos sobre las últimas 1000 solicitudes.' if rows
                                      else 'Sin solicitudes registradas. Recuentos sobre las últimas 1000 solicitudes.')
        self.api_activity_previous.state(['!disabled'] if start else ['disabled'])
        self.api_activity_next.state(['!disabled'] if start + 100 < total else ['disabled'])
