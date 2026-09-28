"""API y procesos automáticos observados, integrados en la navegación de operaciones."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from urllib.parse import urlsplit

from knowledge_orchestrator.services.operations_status import OperationsStatusService
from knowledge_orchestrator.ui.automation_panel import AutomationPanel
from knowledge_orchestrator.ui.dashboard.operaciones import OperacionesMixin
from knowledge_orchestrator.ui.review_batch_dialog import ReviewBatchDialog

API_STATES = {'STOPPED': 'Detenida', 'RUNNING': 'Escuchando en este equipo', 'STOPPING': 'Cerrando', 'ERROR': 'Error'}
API_ERRORS = {'API_CREDENTIALS_NOT_CONFIGURED': 'No hay consumidores con credenciales válidas.',
              'API_BIND_FAILED': ('El puerto está ocupado o restringido. '
                                  'La API y el puente necesitan puertos distintos.'),
              'API_START_FAILED': 'No se pudo iniciar el servidor.', 'API_SERVER_FAILED': 'El servidor se interrumpió.',
              'API_SERVER_STOPPED_UNEXPECTEDLY': 'El servidor dejó de atender solicitudes.',
              'API_STOP_PENDING': 'El cierre sigue pendiente.'}
PERMISSIONS = {'read': 'Lectura', 'query': 'Consultas IA', 'ingest': 'Ingesta',
               'sources': 'Fuentes', 'review': 'Revisión', 'governance': 'Gobernanza'}
#: Lo que permite cada permiso, dicho para quien decide dárselo a otra herramienta.
PERMISSION_HELP = {
    'read': 'Leer documentos, afirmaciones, búsquedas y propuestas',
    'query': 'Hacer consultas con IA sobre el conocimiento',
    'ingest': 'Enviar documentos nuevos al flujo de ingesta (no publica directamente)',
    'sources': 'Registrar y vigilar fuentes web',
    'review': 'Aprobar o rechazar propuestas de cambio en las notas',
    'governance': 'Configurar automatizaciones y su pausa global',
}
ORIGINS = {'application': 'Aplicación', 'environment': 'KO_API_CLIENTS'}
#: Ejemplo copiable. Nunca lleva la credencial real: el portapapeles acaba en
#: historiales y capturas.
CURL_EXAMPLE = 'curl -H "Authorization: Bearer <TU_CREDENCIAL>" {address}/documents'


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
        self._page_heading(page, 'Automatización y API',
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
        bridge_port = urlsplit(self.runtime.obsidian_connection.configured_url()).port
        self.api_port_var = tk.StringVar(value='8767' if bridge_port == 8766 else '8766')
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
            ('name', 'Consumidor', 180), ('scopes', 'Permisos configurados', 250), ('origin', 'Origen', 110),
            ('requests', 'Solicitudes', 90), ('errors', 'Errores', 75), ('seen', 'Última actividad', 200)])
        self.api_consumers_tree.bind('<<TreeviewSelect>>', lambda _event: self._sync_api_consumer_actions())
        self._api_consumer_origins: dict[str, str] = {}
        consumer_actions = ttk.Frame(clients)
        consumer_actions.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(6, 4))
        ttk.Button(consumer_actions, text='Nuevo consumidor…',
                   command=self._open_api_consumer_dialog).pack(side='left', padx=(0, 4))
        self.api_revoke_button = ttk.Button(consumer_actions, text='Revocar acceso',
                                            command=self._revoke_selected_api_consumer)
        self.api_revoke_button.pack(side='left', padx=4)
        self.api_revoke_button.state(['disabled'])
        self.api_probe_button = ttk.Button(consumer_actions, text='Probar acceso local',
                                           command=self._probe_api_access)
        self.api_probe_button.pack(side='left', padx=4)
        self.api_probe_button.state(['disabled'])
        ttk.Button(consumer_actions, text='Copiar ejemplo de uso',
                   command=self._copy_api_example).pack(side='left', padx=4)
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
            'No hay consumidores. Crea uno con «Nuevo consumidor…»; '
            'también se admiten los definidos en KO_API_CLIENTS.'))
        ready = self._startup.done and self._startup.error is None
        self.api_start_button.state(['!disabled'] if ready and api['configured'] and not api['running']
                                    and api['state'] != 'STOPPING' else ['disabled'])
        self.api_stop_button.state(['!disabled'] if api['running'] else ['disabled'])
        self.api_copy_button.state(['!disabled'] if api['running'] else ['disabled'])
        self.api_port_entry.state(['disabled'] if api['running'] else ['!disabled'])
        consumers = [(client['name'], (
            client['name'], ', '.join(PERMISSIONS[scope] for scope in client['scopes'])
            if client['configured'] else 'Sin acceso (revocado o no configurado)',
            ORIGINS.get(client.get('origin', ''), '—'), client['requests'],
            client['errors'], client['last_seen'] or 'Sin actividad')) for client in snapshot['consumers']]
        self._api_consumer_origins = {client['name']: client.get('origin', '') if client['configured'] else ''
                                      for client in snapshot['consumers']}
        self._replace_tree(self.api_consumers_tree, consumers)
        for index, (identifier, _) in enumerate(consumers):
            self.api_consumers_tree.move(identifier, '', index)
        self._sync_api_consumer_actions()
        self.api_probe_button.state(['!disabled'] if api['running'] else ['disabled'])
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

    # ------------------------------------------------------- consumidores

    def _selected_api_consumer(self) -> str | None:
        selection = self.api_consumers_tree.selection()
        return str(selection[0]) if selection else None

    def _sync_api_consumer_actions(self) -> None:
        name = self._selected_api_consumer()
        revocable = name is not None and self._api_consumer_origins.get(name) == 'application'
        self.api_revoke_button.state(['!disabled'] if revocable else ['disabled'])

    def _open_api_consumer_dialog(self) -> None:
        """Alta guiada: nombre y permisos explicados; la credencial se genera al confirmar."""

        dialog = tk.Toplevel(self)
        dialog.title('Nuevo consumidor de la API')
        dialog.configure(bg=self.colors['surface'])
        dialog.transient(self)
        dialog.resizable(False, False)
        self._api_consumer_dialog = dialog
        body = ttk.Frame(dialog, padding=18)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Nombre (sin espacios; p. ej. «obsidian-lector»)').pack(anchor='w')
        name_var = tk.StringVar()
        name_entry = ttk.Entry(body, textvariable=name_var, width=40)
        name_entry.pack(anchor='w', fill='x', pady=(4, 12))
        ttk.Label(body, text='Qué puede hacer').pack(anchor='w')
        scope_vars = {scope: tk.BooleanVar(value=scope == 'read') for scope in PERMISSION_HELP}
        for scope, help_text in PERMISSION_HELP.items():
            ttk.Checkbutton(body, text=f'{PERMISSIONS[scope]} — {help_text}',
                            variable=scope_vars[scope]).pack(anchor='w', pady=1)
        ttk.Label(body, text='Da solo lo necesario: una herramienta que consulta no necesita revisar ni ingerir.',
                  wraplength=460, justify='left').pack(anchor='w', pady=(10, 0))
        self._api_consumer_form = (name_var, scope_vars)
        buttons = ttk.Frame(body)
        buttons.pack(fill='x', pady=(14, 0))

        def create() -> None:
            chosen = [scope for scope, variable in scope_vars.items() if variable.get()]
            if self._create_api_consumer(name_var.get(), chosen) is not None:
                dialog.destroy()

        ttk.Button(buttons, text='Crear y mostrar credencial', style='Accent.TButton',
                   command=create).pack(side='right')
        ttk.Button(buttons, text='Cancelar', command=dialog.destroy).pack(side='right', padx=6)
        name_entry.focus_set()

    def _create_api_consumer(self, name: str, scopes: list[str]) -> str | None:
        """Crea el consumidor y enseña su credencial una sola vez. `None` si no se pudo."""

        controller = self.runtime.api_server
        try:
            _consumer, token = controller.consumers.create(
                name, scopes, reserved_names=controller.environment_client_names())
        except ValueError as error:
            dialog = getattr(self, '_api_consumer_dialog', None)
            parent = dialog if dialog is not None and dialog.winfo_exists() else self
            messagebox.showerror('No se pudo crear el consumidor', str(error), parent=parent)
            return None
        self.status_var.set(f'Consumidor «{name.strip()}» creado. Guarda su credencial ahora.')
        self._show_api_credential(name.strip(), token)
        self._refresh_services()
        return token

    def _show_api_credential(self, name: str, token: str) -> None:
        window = tk.Toplevel(self)
        window.title('Credencial del consumidor')
        window.configure(bg=self.colors['surface'])
        window.transient(self)
        window.resizable(False, False)
        self._api_credential_window = window
        body = ttk.Frame(window, padding=18)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=f'Credencial de «{name}»').pack(anchor='w')
        ttk.Label(body, text='Esta es la única vez que se muestra. La aplicación solo guarda una huella '
                             'irreversible: si la pierdes, revoca este consumidor y crea otro.',
                  wraplength=460, justify='left').pack(anchor='w', pady=(4, 10))
        entry = ttk.Entry(body, width=56)
        entry.insert(0, token)
        entry.state(['readonly'])
        entry.pack(fill='x')

        def copy() -> None:
            self.clipboard_clear()
            self.clipboard_append(token)
            self.status_var.set('Credencial copiada. Pégala en la herramienta que la necesite.')

        buttons = ttk.Frame(body)
        buttons.pack(fill='x', pady=(12, 0))
        ttk.Button(buttons, text='He guardado la credencial', command=window.destroy).pack(side='right')
        ttk.Button(buttons, text='Copiar credencial', style='Accent.TButton',
                   command=copy).pack(side='right', padx=6)
        self._api_credential_copy = copy
        entry.focus_set()
        entry.selection_range(0, 'end')

    def _revoke_selected_api_consumer(self) -> None:
        name = self._selected_api_consumer()
        if name is None:
            return
        if self._api_consumer_origins.get(name) != 'application':
            messagebox.showinfo('Consumidor externo', 'Este consumidor viene de KO_API_CLIENTS: retíralo de esa '
                                'variable y reinicia la API.', parent=self)
            return
        if not messagebox.askyesno('Revocar acceso', f'«{name}» dejará de poder usar la API desde su próxima '
                                   'solicitud. Su actividad registrada se conserva. ¿Continuar?', parent=self):
            return
        self._revoke_api_consumer(name)

    def _revoke_api_consumer(self, name: str) -> bool:
        revoked = self.runtime.api_server.consumers.revoke(name)
        self.status_var.set(f'Acceso de «{name}» revocado.' if revoked else f'«{name}» ya no tenía acceso.')
        self._refresh_services()
        return revoked

    def _probe_api_access(self) -> None:
        """Petición real al listener: con credencial dice quién eres; sin ella, que exige una."""

        token = simpledialog.askstring(
            'Probar acceso local', 'Pega una credencial para comprobarla, o deja vacío para comprobar solo '
            'que la API responde. No se guarda.', show='•', parent=self)
        if token is None:
            return
        self.api_probe_button.state(['disabled'])
        results: queue.SimpleQueue = queue.SimpleQueue()
        controller = self.runtime.api_server
        credential = token.strip() or None
        threading.Thread(target=lambda: results.put(controller.probe(credential)),
                         name='api-probe', daemon=True).start()
        self._poll_api_probe(results, credential is not None)

    def _poll_api_probe(self, results: queue.SimpleQueue, with_token: bool) -> None:
        try:
            outcome = results.get_nowait()
        except queue.Empty:
            self.after(100, lambda: self._poll_api_probe(results, with_token))
            return
        self.api_probe_button.state(['!disabled'])
        self._report_api_probe(outcome, with_token)

    def _report_api_probe(self, outcome: dict, with_token: bool) -> str:
        status = outcome.get('status')
        if not outcome.get('reachable'):
            message = 'La API no responde en este equipo. Iníciala y vuelve a probar.'
        elif not with_token:
            message = ('La API responde y exige credencial, como debe.' if status == 401
                       else f'La API respondió {status} sin credencial; revisa su configuración.')
        elif status == 200:
            message = f"Acceso correcto como «{outcome.get('client') or 'consumidor'}»."
        elif status == 401:
            message = 'Credencial no válida o revocada.'
        else:
            message = f'La API respondió {status}.'
        self.api_hint_var.set(message)
        self.status_var.set(message)
        return message

    def _copy_api_example(self) -> None:
        address = self._services_snapshot.get('api', {}).get('address') or 'http://127.0.0.1:8766/api/v1'
        self.clipboard_clear()
        self.clipboard_append(CURL_EXAMPLE.format(address=address))
        self.status_var.set('Ejemplo copiado; sustituye <TU_CREDENCIAL> por la credencial del consumidor.')
