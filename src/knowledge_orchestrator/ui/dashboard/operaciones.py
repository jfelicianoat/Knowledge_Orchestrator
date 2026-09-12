"""Pipeline navegable y actividad durable en el diseño de escritorio existente.

THESIS: cada etapa lleva al trabajo que la explica.
OWN-WORLD: componentes ttk, superficies grafito y foco cian heredados.
STORY: detectar una novedad, seguir su análisis y abrir la decisión correspondiente.
FIRST VIEWPORT: etapas en Resumen; filtros, registro y detalle en Operaciones.
FORM: extensión del registro maestro-detalle aprobado, sin una nueva identidad.
"""
from __future__ import annotations

import queue
import sqlite3
import threading
import tkinter as tk
from functools import partial
from tkinter import messagebox, ttk

from knowledge_orchestrator.ui.dashboard.conocimiento import ConocimientoMixin
from knowledge_orchestrator.ui.dashboard.estilo import FONT, FONT_SEMIBOLD, TONES
from knowledge_orchestrator.ui.dashboard.fuentes import CHANGE_LABELS, source_time
from knowledge_orchestrator.ui.dashboard.revision import RELATION_LABELS

STAGES = {'Cambios': 'changes', 'Análisis': 'analysis', 'Propuestas': 'proposals',
          'Histórico de decisiones': 'history', 'Actividad': 'activity'}
SCOPES = {'Pendientes': 'pending', 'Con incidencias': 'errors', 'Todos': 'all'}
STATUS_LABELS = {**CHANGE_LABELS, 'PENDING_COMPARISON': 'Por comparar', 'PENDING_REVIEW': 'Por revisar',
                 'APPLYING': 'Publicando', 'APPLIED': 'Aplicado', 'REJECTED': 'Descartado',
                 'CONFLICT': 'Conflicto', 'ERROR': 'Error', 'SUCCESS': 'Completado',
                 'SUBMITTING': 'Enviando', 'QUEUED': 'En cola', 'PROCESSING': 'Analizando', 'READY': 'En espera'}


class OperacionesMixin(ConocimientoMixin):
    def _build_operations(self) -> None:
        self._flow_items: dict[str, dict] = {}
        self._flow_offset = 0
        self._flow_kind = 'changes'
        self._flow_revision_id: int | None = None
        page = self._new_page('operations')
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        self._page_heading(page, 'Actividad',
                           'Sigue cada novedad hasta su análisis, revisión y publicación.')
        controls = ttk.Frame(page, style='Dark.TFrame')
        controls.grid(row=1, column=0, sticky='ew', padx=24, pady=(0, 12))
        self.flow_stage = tk.StringVar(value='Cambios')
        self.flow_scope = tk.StringVar(value='Pendientes')
        for column, (label, variable, values) in enumerate((('Etapa', self.flow_stage, STAGES),
                                                           ('Mostrar', self.flow_scope, SCOPES))):
            ttk.Label(controls, text=label, style='Dark.TLabel').grid(row=0, column=column * 2, padx=(0, 8))
            selector = ttk.Combobox(controls, textvariable=variable, values=list(values), state='readonly',
                                    style='Dark.TCombobox', width=23)
            selector.grid(row=0, column=column * 2 + 1, padx=(0, 20))
            if column == 1:
                self.flow_scope_selector = selector
            selector.bind('<<ComboboxSelected>>', lambda _event: self._reset_flow())
        panes = ttk.Panedwindow(page, orient='vertical')
        panes.grid(row=2, column=0, sticky='nsew', padx=24)
        upper, lower = ttk.Frame(panes, style='Dark.TFrame'), ttk.Frame(panes, style='Dark.TFrame')
        panes.add(upper, weight=2)
        panes.add(lower, weight=3)
        upper.columnconfigure(0, weight=1)
        upper.rowconfigure(0, weight=1)
        self.flow_tree = ttk.Treeview(upper, columns=('status', 'updated'), show='tree headings',
                                     selectmode='browse', style='Dark.Treeview', height=6)
        self.flow_tree.heading('#0', text='Documento / actividad')
        self.flow_tree.heading('status', text='Estado')
        self.flow_tree.heading('updated', text='Actualizado')
        self.flow_tree.column('#0', width=500, minwidth=180)
        self.flow_tree.column('status', width=190, minwidth=110)
        self.flow_tree.column('updated', width=180, minwidth=100)
        self.flow_tree.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(upper, orient='vertical', command=self.flow_tree.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.flow_tree.configure(yscrollcommand=scroll.set)
        self.flow_tree.bind('<<TreeviewSelect>>', lambda _event: self._select_flow())
        lower.columnconfigure(0, weight=1)
        lower.rowconfigure(0, weight=1)
        self.flow_detail = tk.Text(lower, wrap='word', height=9, bg=self.colors['raised'], fg=self.colors['text'],
                                   padx=18, pady=14, font=('Segoe UI', 10), relief='flat')
        self.flow_detail.grid(row=0, column=0, sticky='nsew', pady=(12, 0))
        detail_scroll = ttk.Scrollbar(lower, orient='vertical', command=self.flow_detail.yview)
        detail_scroll.grid(row=0, column=1, sticky='ns', pady=(12, 0))
        self.flow_detail.configure(yscrollcommand=detail_scroll.set)
        footer = ttk.Frame(page, style='Dark.TFrame')
        footer.grid(row=3, column=0, sticky='ew', padx=24, pady=12)
        footer.columnconfigure(0, weight=1)
        self.flow_summary = tk.StringVar()
        ttk.Label(footer, textvariable=self.flow_summary, style='Muted.TLabel').grid(row=0, column=0, sticky='w')
        self.flow_previous = ttk.Button(footer, text='Anterior', command=lambda: self._page_flow(-1))
        self.flow_previous.grid(row=0, column=1, padx=4)
        self.flow_next = ttk.Button(footer, text='Siguiente', command=lambda: self._page_flow(1))
        self.flow_next.grid(row=0, column=2, padx=4)
        actions = ttk.Frame(page, style='Dark.TFrame')
        actions.grid(row=4, column=0, sticky='ew', padx=24, pady=(0, 14))
        self.flow_open = ttk.Button(actions, text='Abrir detalle', command=self._open_flow_item)
        self.flow_open.pack(side='left')
        self.flow_ingest = ttk.Button(actions, text='Incorporar novedad', command=self._ingest_flow_change)
        self.flow_ingest.pack(side='left', padx=8)
        self.flow_revision = ttk.Button(actions, text='Ver versión anterior', command=self._show_flow_revision)
        self.flow_revision.pack(side='left')
        self.flow_audit = ttk.Button(actions, text='Ver trazabilidad', command=self._audit_flow_proposal)
        self.flow_audit.pack(side='left', padx=8)
        ttk.Button(actions, text='Volver al detalle', command=self._return_flow_detail).pack(side='left', padx=8)
        self._refresh_flow()
        self._build_pipeline()

    def _reset_flow(self) -> None:
        self._flow_offset = 0
        kind = STAGES[self.flow_stage.get()]
        if kind != self._flow_kind:
            self._flow_revision_id = None
            self.flow_tree.selection_remove(*self.flow_tree.selection())
            if kind in {'history', 'activity'}:
                self.flow_scope.set('Todos')
        self._flow_kind = kind
        self.flow_scope_selector.configure(state='disabled' if kind == 'history' else 'readonly')
        self._refresh_flow()

    def _page_flow(self, direction: int) -> None:
        self._flow_offset = max(0, self._flow_offset + direction * 100)
        self._refresh_flow()

    def _refresh_flow(self) -> None:
        try:
            snapshot = self.operations.flow(self._flow_kind, scope=SCOPES[self.flow_scope.get()],
                                             offset=self._flow_offset)
        except (ValueError, sqlite3.Error):
            self._flow_items = {}
            self._replace_tree(self.flow_tree, [])
            self.flow_summary.set('No se pudo consultar la actividad. Actualiza para reintentar.')
            self.flow_previous.state(['disabled'])
            self.flow_next.state(['disabled'])
            self._select_flow()
            return
        self._flow_offset = snapshot['offset']
        self._flow_items = {str(row['id']): row for row in snapshot['items']}
        self._replace_tree(self.flow_tree, [(key, (
            STATUS_LABELS.get(row['status'], row['status']),
            source_time(row['updated']) if isinstance(row['updated'], (int, float)) else row['updated'],
        )) for key, row in self._flow_items.items()],
            texts={key: row['title'] for key, row in self._flow_items.items()})
        self.flow_summary.set(f"{self._flow_offset + 1}–{self._flow_offset + len(snapshot['items'])} "
                              f"de {snapshot['total']} registros" if snapshot['total'] else
                              'No hay registros con estos filtros. Prueba «Todos» u otra etapa.')
        self.flow_previous.state(['!disabled'] if self._flow_offset else ['disabled'])
        self.flow_next.state(['!disabled'] if self._flow_offset + 100 < snapshot['total'] else ['disabled'])
        self._select_flow()

    def _flow_item(self) -> dict | None:
        selected = self.flow_tree.selection()
        return self._flow_items.get(selected[0]) if selected else None

    def _select_flow(self) -> None:
        row = self._flow_item()
        for button in (self.flow_open, self.flow_ingest, self.flow_revision, self.flow_audit):
            button.state(['disabled'])
        if row is None:
            self._flow_revision_id = None
            self._flow_text('Selecciona un registro para seguir su procedencia, estado y siguiente paso.')
            return
        text = row['title'] + '\n\n' + STATUS_LABELS.get(row['status'], row['status'])
        if self._flow_revision_id != row['id']:
            self._flow_revision_id = None
        if row.get('capture_id'):
            self.flow_open.configure(text='Abrir documento')
            self.flow_open.state(['!disabled'])
        try:
            if self._flow_kind == 'changes':
                change = self.runtime.sources.repository.change(row['id'])
                flow = self.operations.change_flow(row['id'])
                text += (f"\n\nFuente: {row['source_name']}\n{change['source_url']}"
                         f"\nConfianza configurada: {change['provenance']['trust_level']}/100"
                         f"\n\nDocumento: {flow['capture_status'] or 'Todavía no ingerido'}"
                         f"\nNotas publicadas: {len(flow['note_ids'])} · Propuestas: {len(flow['candidate_ids'])}"
                         '\nIncorporar inicia el análisis; las modificaciones de conocimiento se revisan después.'
                         '\n\nContenido detectado\n' + change['content'][:60000])
                if len(change['content']) > 60000:
                    text += '\n\nVista parcial. Consulta la fuente para leer el contenido completo.'
                if row['status'] == 'REVIEW':
                    self.flow_ingest.state(['!disabled'])
                if not row.get('capture_id'):
                    self.flow_open.configure(text='Abrir fuente')
                    self.flow_open.state(['!disabled'])
            elif self._flow_kind == 'analysis':
                label = 'Extracción de afirmaciones' if row['kind'] == 'EXTRACT' else 'Comparación de evidencia'
                text += ('\n\n' + label
                         + f"\nTarea: {row['id']}\nIntentos: {row['attempt']}"
                         + f"\nTarea del Broker: {row['broker_task_id'] or 'Aún no enviada'}")
            elif self._flow_kind in {'proposals', 'history'}:
                self.flow_audit.state(['!disabled'])
                review = self.runtime.semantic_maintenance.proposal_detail(row['id'])
                assessment = review['assessment'] or {}
                text += ('\n\n' + RELATION_LABELS.get(row['relation'], row['relation'])
                         + '\n' + (row['rationale'] or 'La comparación todavía no ha terminado.')
                         + '\n\nAntes\n' + assessment.get('before', 'Sin evaluación')
                         + '\n\nPropuesto\n' + (assessment.get('proposed') or 'Sin cambio documental')
                         + f"\n\nRevisión: {review['revision']} · Decisión: {row['reviewed_by'] or 'Pendiente'}")
                if row['status'] in {'PENDING_REVIEW', 'CONFLICT'}:
                    self.flow_open.configure(text='Abrir revisión')
                if row['status'] == 'APPLIED':
                    self.flow_revision.state(['!disabled'])
                    if self._flow_revision_id == row['id']:
                        text = ('Versión anterior conservada · ' + row['title'] + '\n\n'
                                + self.runtime.semantic_repository.revision_content(row['id']))
            if row.get('error_code'):
                text += '\n\nIncidencia registrada\n' + row['error_code']
            self._flow_text(text)
        except (ValueError, LookupError, sqlite3.Error):
            self._flow_text('El registro cambió o no está disponible. Actualiza para volver a consultarlo.')
            for button in (self.flow_open, self.flow_ingest, self.flow_revision, self.flow_audit):
                button.state(['disabled'])

    def _audit_flow_proposal(self):
        row = self._flow_item()
        if row and self._flow_kind in {'proposals', 'history'}:
            self._open_proposal_audit(row['id'])

    def _flow_text(self, value: str) -> None:
        if self.flow_detail.get('1.0', 'end-1c') == value:
            return
        self.flow_detail.configure(state='normal')
        self.flow_detail.delete('1.0', 'end')
        self.flow_detail.insert('1.0', value)
        self.flow_detail.configure(state='disabled')

    def _open_flow_item(self) -> None:
        row = self._flow_item()
        if row is None:
            return
        if self._flow_kind in {'proposals', 'history'} and row['status'] in {'PENDING_REVIEW', 'CONFLICT'}:
            self._refresh_reviews()
            identifier = str(row['id'])
            if identifier in self._review_items:
                self._show_page('review')
                self.review_tree.selection_set(identifier)
                self._select_review()
        elif row.get('capture_id'):
            self.search_var.set('')
            self._work_items = {item.capture_id: item for item in self.snapshots.work_items()}
            self._work_filter = 'all'
            self._selected_work_id = row['capture_id']
            self._selected_work_ids = (row['capture_id'],)
            self._show_page('work')
            self._refresh_work_list()
        elif self._flow_kind == 'changes':
            self._show_page('sources')
            self._refresh_sources()
            self.sources_tree.selection_set(str(row['source_id']))
            self._refresh_source_changes()

    def _ingest_flow_change(self) -> None:
        row = self._flow_item()
        if row is None or self._flow_kind != 'changes':
            return
        try:
            self.runtime.sources.repository.queue_ingestion(row['id'], actor='ui')
            self._refresh_flow()
        except (ValueError, sqlite3.Error) as error:
            messagebox.showerror('No se pudo incorporar la novedad', str(error), parent=self)

    def _show_flow_revision(self) -> None:
        row = self._flow_item()
        if row is None or self._flow_kind not in {'proposals', 'history'} or row['status'] != 'APPLIED':
            return
        try:
            content = self.runtime.semantic_repository.revision_content(row['id'])
            self._flow_revision_id = row['id']
            self._flow_text('Versión anterior conservada · ' + row['title'] + '\n\n' + content)
        except (ValueError, sqlite3.Error) as error:
            self._flow_text('No se pudo recuperar esta revisión.\n' + str(error))

    def _return_flow_detail(self) -> None:
        self._flow_revision_id = None
        self._select_flow()

    def _open_flow(self, kind: str, *, scope: str = 'pending') -> None:
        self.flow_stage.set(next(label for label, value in STAGES.items() if value == kind))
        self.flow_scope.set(next(label for label, value in SCOPES.items() if value == scope))
        self._reset_flow()
        self._show_page('operations')

    def _build_pipeline(self) -> None:
        """Etapas como nodos numerados y unidos: se lee de izquierda a derecha."""

        c = self.colors
        self.pipeline_vars: dict[str, tk.StringVar] = {}
        self._pipeline_nodes: dict[str, tuple[tk.Canvas, int, int]] = {}
        self._pipeline_refreshing = False
        self._pipeline_results: queue.SimpleQueue[dict | Exception] = queue.SimpleQueue()
        stages = [('sources', 'Fuentes', lambda: self._show_page('sources')),
                  ('changes', 'Cambios', lambda: self._open_flow('changes')),
                  ('analysis', 'Análisis', lambda: self._open_flow('analysis')),
                  ('proposals', 'Propuestas', lambda: self._open_flow('proposals')),
                  ('review', 'Revisión', lambda: self._show_page('review')),
                  ('published', 'Publicación', lambda: self._show_page('library'))]
        host = self.lifecycle_host
        for index, (key, label, action) in enumerate(stages):
            column = index * 2
            canvas = tk.Canvas(host, width=46, height=46, bg=c['raised'], highlightthickness=0, cursor='hand2')
            canvas.grid(row=0, column=column, padx=6, pady=(6, 2))
            oval = canvas.create_oval(3, 3, 43, 43, outline=c['border'], width=2)
            number = canvas.create_text(23, 23, text='0', fill=c['faint'], font=(FONT_SEMIBOLD, 13))
            caption = tk.Label(host, text=label, bg=c['raised'], fg=c['muted'], font=(FONT, 9), cursor='hand2')
            caption.grid(row=1, column=column, padx=2, pady=(0, 4))
            for widget in (canvas, caption):
                widget.bind('<Button-1>', partial(self._invoke, action))
            self.pipeline_vars[key] = tk.StringVar(value='0')
            self._pipeline_nodes[key] = (canvas, oval, number)
            if index < len(stages) - 1:
                host.columnconfigure(column + 1, weight=1)
                tk.Frame(host, bg=c['border'], height=2).grid(row=0, column=column + 1, sticky='ew')
        self.lifecycle_summary = tk.StringVar(value='Conocimiento y cambios según el registro local.')
        tk.Label(host, textvariable=self.lifecycle_summary, bg=c['raised'], fg=c['faint'], font=(FONT, 9),
                 anchor='w').grid(row=2, column=0, columnspan=len(stages) * 2 - 1, sticky='w', pady=(8, 12))

    def _set_stage(self, key: str, count: int) -> None:
        canvas, oval, number = self._pipeline_nodes[key]
        color = {'published': TONES['success'][1], 'review': TONES['warning'][1]}.get(key, self.colors['accent'])
        active = count > 0
        canvas.itemconfigure(oval, outline=color if active else self.colors['border'])
        canvas.itemconfigure(number, text=str(count), fill=color if active else self.colors['faint'])
        self.pipeline_vars[key].set(str(count))

    def _refresh_dashboard(self) -> None:
        super()._refresh_dashboard()
        for key in ('review', 'published'):
            try:
                self._set_stage(key, int(self.dashboard_vars[key].get()))
            except ValueError:
                pass
        if self._pipeline_refreshing:
            return
        self._pipeline_refreshing = True
        operations, results = self.operations, self._pipeline_results

        def load() -> None:
            try:
                results.put(operations.refresh_counts())
            except Exception as error:
                results.put(error)

        threading.Thread(target=load, name='knowledge-pipeline-read', daemon=True).start()
        self.after(50, self._poll_pipeline)

    def _poll_pipeline(self) -> None:
        try:
            result = self._pipeline_results.get_nowait()
        except queue.Empty:
            self.after(50, self._poll_pipeline)
            return
        self._pipeline_refreshing = False
        if isinstance(result, Exception):
            self.lifecycle_summary.set('No se pudieron actualizar los indicadores. Usa Actualizar para reintentar.')
            return
        counts = result
        for key in ('sources', 'changes', 'analysis', 'proposals'):
            self._set_stage(key, int(counts[key]))
        self.lifecycle_summary.set(f"{counts['current']} afirmaciones vigentes · {counts['historical']} históricas · "
                                   f"{counts['review']} en revisión · {counts['contradictions']} contradicciones · "
                                   f"{counts['source_errors']} fuentes con errores")
