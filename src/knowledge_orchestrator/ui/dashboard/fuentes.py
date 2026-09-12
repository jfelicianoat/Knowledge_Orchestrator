"""Configuración y revisión de fuentes; ninguna descarga se ejecuta en Tk."""
from __future__ import annotations

import tkinter as tk
import uuid
from dataclasses import asdict
from datetime import datetime
from tkinter import messagebox, ttk

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.domain.monitoring import SourceConfig
from knowledge_orchestrator.ui.dashboard.configuracion import ConfiguracionMixin

ROLE_LABELS = {'Documentación oficial': 'official_documentation', 'Repositorio oficial': 'official_repository',
               'Blog oficial': 'official_blog', 'Fuente secundaria': 'secondary', 'Web genérica': 'generic'}
POLICY_LABELS = {'Revisar primero': 'review', 'Incorporar novedades': 'ingest'}
CHANGE_LABELS = {'REVIEW': 'Pendiente de revisión', 'READY': 'Esperando ingesta', 'DELIVERED': 'En flujo documental'}


def source_time(value) -> str:
    return datetime.fromtimestamp(value).strftime('%d/%m %H:%M') if value else 'Sin comprobar'


def source_health(source: dict) -> str:
    if not source['config']['enabled']:
        return 'Pausada'
    if source['check_id']:
        return 'Comprobando'
    code = source['last_error_code']
    if code:
        return {'NETWORK_DENIED': 'Red bloqueada', 'NETWORK_ERROR': 'Sin conexión', 'TIMEOUT': 'Tiempo agotado',
                'ADDRESS_NOT_PUBLIC': 'Dirección no pública', 'CREDENTIAL_UNAVAILABLE': 'Falta credencial',
                'INVALID_FEED': 'Feed no válido', 'HTTP_401': 'Acceso denegado', 'HTTP_403': 'Acceso denegado',
                'HTTP_404': 'Página no encontrada'}.get(code, 'Requiere atención')
    return 'Al día' if source['last_checked_at'] else 'Esperando primera comprobación'


class FuentesMixin(ConfiguracionMixin):
    def _build_sources(self) -> None:
        page = self._new_page('sources')
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)
        self._page_heading(page, 'Fuentes vigiladas',
                           'Detecta novedades. La confianza describe la fuente; cada afirmación necesita evidencia.')
        bar = ttk.Frame(page)
        bar.grid(row=1, column=0, sticky='ew', padx=24)
        ttk.Button(bar, text='Añadir fuente', command=self._edit_source).pack(side='left', padx=(0, 8))
        ttk.Button(bar, text='Editar seleccionada', command=lambda: self._edit_source(edit=True)).pack(side='left')
        ttk.Button(bar, text='Comprobar ahora', command=self._check_source).pack(side='left', padx=8)
        self.source_summary = tk.StringVar(value='Sin fuentes. Añade una URL o un feed RSS/Atom para empezar.')
        ttk.Label(page, textvariable=self.source_summary).grid(row=2, column=0, sticky='w', padx=24, pady=10)
        panes = ttk.Panedwindow(page, orient='vertical')
        panes.grid(row=3, column=0, sticky='nsew', padx=24, pady=(0, 16))
        upper = ttk.Frame(panes)
        lower = ttk.Frame(panes)
        panes.add(upper, weight=1)
        panes.add(lower, weight=2)
        upper.columnconfigure(0, weight=1)
        upper.rowconfigure(0, weight=1)
        self.sources_tree = ttk.Treeview(upper, columns=('name', 'kind', 'health', 'checked', 'next', 'policy'),
                                         show='headings', selectmode='browse', height=5)
        for key, label, width in [('name', 'Fuente', 220), ('kind', 'Tipo', 65), ('health', 'Estado', 180),
                                   ('checked', 'Última comprobación', 135), ('next', 'Próxima', 100),
                                   ('policy', 'Novedades', 160)]:
            self.sources_tree.heading(key, text=label)
            self.sources_tree.column(key, width=width, minwidth=60)
        self.sources_tree.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(upper, command=self.sources_tree.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.sources_tree.configure(yscrollcommand=scroll.set)
        self.sources_tree.bind('<<TreeviewSelect>>', lambda _event: self._refresh_source_changes())
        lower.columnconfigure(0, weight=1)
        lower.columnconfigure(1, weight=2)
        lower.rowconfigure(1, weight=1)
        ttk.Label(lower, text='Novedades de la fuente seleccionada').grid(row=0, column=0, sticky='w', pady=8)
        ttk.Button(lower, text='Incorporar novedad seleccionada', command=self._ingest_source_change).grid(
            row=0, column=1, sticky='e', pady=8)
        change_list = ttk.Frame(lower)
        change_list.grid(row=1, column=0, sticky='nsew', padx=(0, 12))
        change_list.columnconfigure(0, weight=1)
        change_list.rowconfigure(0, weight=1)
        self.source_changes_tree = ttk.Treeview(change_list, columns=('title', 'status'), show='headings',
                                                selectmode='browse', height=6)
        self.source_changes_tree.heading('title', text='Novedad')
        self.source_changes_tree.heading('status', text='Estado')
        self.source_changes_tree.column('title', width=210)
        self.source_changes_tree.column('status', width=155)
        self.source_changes_tree.grid(row=0, column=0, sticky='nsew')
        change_scroll = ttk.Scrollbar(change_list, command=self.source_changes_tree.yview)
        change_scroll.grid(row=0, column=1, sticky='ns')
        self.source_changes_tree.configure(yscrollcommand=change_scroll.set)
        self.source_changes_tree.bind('<<TreeviewSelect>>', lambda _event: self._preview_source_change())
        preview = ttk.Frame(lower)
        preview.grid(row=1, column=1, sticky='nsew')
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        self.source_preview = tk.Text(preview, wrap='word', height=8, width=40, state='disabled',
                                      bg=self.colors['raised'], fg=self.colors['text'], relief='flat', padx=14,
                                      pady=12, font=('Segoe UI', 10), highlightthickness=0)
        self.source_preview.grid(row=0, column=0, sticky='nsew')
        preview_scroll = ttk.Scrollbar(preview, command=self.source_preview.yview)
        preview_scroll.grid(row=0, column=1, sticky='ns')
        self.source_preview.configure(yscrollcommand=preview_scroll.set)
        self._refresh_sources()

    def _refresh_sources(self) -> None:
        rows = self.runtime.sources.repository.list_sources(limit=1000)
        self._replace_tree(self.sources_tree, [(str(row['source_id']), (
            row['config']['name'], 'Web' if row['config']['kind'] == 'web' else 'RSS/Atom', source_health(row),
            source_time(row['last_checked_at']),
            source_time(row['next_check_at']) if row['next_check_at'] else 'En cola',
            'Revisar primero' if row['config']['ingestion_policy'] == 'review' else 'Incorporar novedades',
        )) for row in rows])
        self.source_summary.set(f'{len(rows)} fuentes · Selecciona una para ver sus novedades.' if rows else
                                'Sin fuentes. Añade una URL o un feed RSS/Atom para empezar.')
        self._refresh_source_changes()

    def _refresh_source_changes(self) -> None:
        selected = self.sources_tree.selection()
        rows = self.runtime.sources.repository.changes(source_id=int(selected[0]), limit=1000) if selected else []
        self._replace_tree(self.source_changes_tree, [(row['change_id'], (
            row['title'], 'Ingesta: reintento pendiente' if row['delivery_error'] else CHANGE_LABELS[row['status']]))
                                                      for row in rows])
        self._preview_source_change()

    def _preview_source_change(self) -> None:
        selected = self.source_changes_tree.selection()
        text = 'Selecciona una novedad para leer su contenido y procedencia.'
        if selected:
            change = self.runtime.sources.repository.change(selected[0])
            origin = change['provenance']
            text = (f"{change['title']}\n{change['source_url']}\n\n"
                    f"Detectado: {source_time(change['observed_at'])} · {CHANGE_LABELS[change['status']]}\n"
                    f"Confianza de fuente: {origin['trust_level']}/100 · Revisión {change['source_revision']}\n"
                    f"Ámbito: {origin['scope'] or 'General'}\n"
                    'Incorporar inicia el análisis documental. Las propuestas de cambio mantienen su revisión.\n\n'
                    + change['content'])
        if self.source_preview.get('1.0', 'end-1c') != text:
            self.source_preview.configure(state='normal')
            self.source_preview.delete('1.0', 'end')
            self.source_preview.insert('1.0', text)
            self.source_preview.configure(state='disabled')

    def _check_source(self) -> None:
        selected = self.sources_tree.selection()
        if not selected:
            self.source_summary.set('Selecciona una fuente para comprobarla.')
            return
        try:
            self.runtime.sources.repository.request_check(int(selected[0]), actor='ui', key=uuid.uuid4().hex)
            self.source_summary.set('Comprobación solicitada; el resultado aparecerá en esta vista.')
        except KnowledgeConflict as error:
            messagebox.showinfo('Comprobación pendiente', str(error), parent=self)

    def _ingest_source_change(self) -> None:
        selected = self.source_changes_tree.selection()
        if selected:
            self.runtime.sources.repository.queue_ingestion(selected[0], actor='ui')
            self._refresh_source_changes()

    def _edit_source(self, *, edit: bool = False) -> None:
        selected = self.sources_tree.selection()
        if edit and not selected:
            self.source_summary.set('Selecciona una fuente para editarla.')
            return
        existing = self.runtime.sources.repository.get(int(selected[0])) if edit else None
        config = existing['config'] if existing else asdict(SourceConfig('Nueva fuente', 'web', 'https://example.org'))
        dialog = tk.Toplevel(self)
        dialog.title('Editar fuente' if edit else 'Añadir fuente')
        dialog.transient(self)
        dialog.columnconfigure(1, weight=1)
        fields: dict[str, tk.StringVar] = {}
        choices = {'kind': {'Web': 'web', 'RSS/Atom': 'rss'}, 'source_role': ROLE_LABELS,
                   'ingestion_policy': POLICY_LABELS}
        labels = [('name', 'Nombre'), ('location', 'URL'), ('kind', 'Tipo'),
                  ('interval_seconds', 'Frecuencia (segundos, mínimo 60)'), ('scope', 'Ámbito'),
                  ('trust_level', 'Confianza de fuente (0–100)'), ('source_role', 'Categoría'),
                  ('ingestion_policy', 'Al detectar novedades'),
                  ('credential_env', 'Referencia de credencial (opcional)')]
        for row, (key, label) in enumerate(labels):
            value = config[key]
            if key in choices:
                value = next(label for label, code in choices[key].items() if code == value)
            variable = tk.StringVar(value=str(value))
            fields[key] = variable
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky='w', padx=16, pady=7)
            widget = ttk.Combobox(dialog, textvariable=variable, values=list(choices[key]), state='readonly') \
                if key in choices else ttk.Entry(dialog, textvariable=variable, width=52)
            widget.grid(row=row, column=1, sticky='ew', padx=16, pady=7)
        enabled = tk.BooleanVar(value=config['enabled'])
        ttk.Checkbutton(dialog, text='Fuente activa', variable=enabled).grid(row=9, column=1, sticky='w', padx=16)
        ttk.Label(dialog, text='La ingesta automática no aprueba cambios en conocimiento.\n'
                              'Credenciales: escribe solo el nombre KO_SOURCE_SECRET_…, nunca el token.',
                  wraplength=580).grid(row=10, column=0, columnspan=2, sticky='w', padx=16, pady=12)

        def save():
            try:
                values = {key: choices[key][var.get()] if key in choices else var.get().strip()
                          for key, var in fields.items()}
                updated = SourceConfig(**{**values, 'enabled': enabled.get(),
                                          'interval_seconds': int(values['interval_seconds']),
                                          'trust_level': int(values['trust_level'])})
                if existing:
                    self.runtime.sources.repository.update(existing['source_id'], updated,
                                                           expected_revision=existing['revision'], actor='ui')
                else:
                    self.runtime.sources.repository.create(updated, actor='ui', key=uuid.uuid4().hex)
            except (ValueError, KnowledgeConflict) as error:
                messagebox.showerror('No se pudo guardar la fuente', str(error), parent=dialog)
                return
            self._refresh_sources()
            dialog.destroy()

        ttk.Button(dialog, text='Guardar fuente', command=save).grid(row=11, column=1, sticky='e', padx=16, pady=16)
