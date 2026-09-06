"""Exploración integrada de conocimiento.

THESIS: una afirmación lleva a su evidencia y evolución, dentro de la biblioteca.
OWN-WORLD: grafito, Segoe UI y controles ttk existentes; cian solo para acción/foco.
STORY: filtrar vigencia, leer evidencia y recorrer la sucesión sin consultar logs.
FIRST VIEWPORT: filtros arriba, afirmaciones a la izquierda, evidencia a la derecha.
FORM: extensión maestro-detalle de la interfaz aprobada; sin cambio de identidad.
"""
from __future__ import annotations

import queue
import sqlite3
import threading
import tkinter as tk
from tkinter import ttk

from knowledge_orchestrator.ui.dashboard.fuentes import FuentesMixin
from knowledge_orchestrator.ui.operations_snapshots import OperationsSnapshots

STATE_LABELS = {'CURRENT': 'Vigente', 'HISTORICAL': 'Histórico', 'SUPERSEDED': 'Sustituido',
                'DISPUTED': 'Disputado', 'UNCERTAIN': 'Incierto', 'REVIEW_REQUIRED': 'Necesita revisión'}
FILTERS = {'Vigente': 'current', 'Histórico': 'historical', 'En revisión': 'review', 'Todos': 'all'}


class ConocimientoMixin(FuentesMixin):
    def _build_knowledge(self) -> None:
        self.operations = OperationsSnapshots(self.runtime.database)
        self._knowledge_offset = 0
        self._knowledge_applied_query = ''
        self._knowledge_applied_state = 'current'
        self._knowledge_refreshing = False
        self._knowledge_results: queue.SimpleQueue[tuple[tuple, dict | Exception]] = queue.SimpleQueue()
        self._knowledge_items: dict[str, dict] = {}
        self._knowledge_detail_id: int | None = None
        page = self._new_page('knowledge')
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        self._page_heading(page, 'Conocimiento', 'Explora afirmaciones, evidencia y evolución por estado o entidad.')
        filters = ttk.Frame(page, style='Dark.TFrame')
        filters.grid(row=1, column=0, sticky='ew', padx=24, pady=(0, 12))
        filters.columnconfigure(3, weight=1)
        ttk.Label(filters, text='Estado', style='Dark.TLabel').grid(row=0, column=0, padx=(0, 8))
        self.knowledge_state = tk.StringVar(value='Vigente')
        states = ttk.Combobox(filters, textvariable=self.knowledge_state, values=list(FILTERS),
                              state='readonly', width=16, style='Dark.TCombobox')
        states.grid(row=0, column=1, padx=(0, 20))
        states.bind('<<ComboboxSelected>>', lambda _event: self._reset_knowledge())
        ttk.Label(filters, text='Entidad o texto', style='Dark.TLabel').grid(row=0, column=2, padx=(0, 8))
        self.knowledge_query = tk.StringVar()
        search = self.knowledge_search_entry = ttk.Entry(
            filters, textvariable=self.knowledge_query, style='Dark.TEntry')
        search.grid(row=0, column=3, sticky='ew')
        search.bind('<Return>', lambda _event: self._reset_knowledge())
        ttk.Button(filters, text='Buscar', command=self._reset_knowledge).grid(row=0, column=4, padx=(8, 0))
        panes = ttk.Panedwindow(page, orient='horizontal')
        panes.grid(row=2, column=0, sticky='nsew', padx=24)
        left, right = ttk.Frame(panes, style='Dark.TFrame'), ttk.Frame(panes, style='Dark.TFrame')
        panes.add(left, weight=3)
        panes.add(right, weight=4)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)
        self.knowledge_tree = ttk.Treeview(left, columns=('state', 'note'), show='tree headings',
                                          selectmode='browse', style='Dark.Treeview')
        self.knowledge_tree.heading('#0', text='Afirmación')
        self.knowledge_tree.heading('state', text='Vigencia')
        self.knowledge_tree.heading('note', text='Nota')
        self.knowledge_tree.column('#0', width=310, minwidth=150)
        self.knowledge_tree.column('state', width=130, minwidth=100)
        self.knowledge_tree.column('note', width=140, minwidth=100)
        self.knowledge_tree.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(left, orient='vertical', command=self.knowledge_tree.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.knowledge_tree.configure(yscrollcommand=scroll.set)
        horizontal = ttk.Scrollbar(left, orient='horizontal', command=self.knowledge_tree.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.knowledge_tree.configure(xscrollcommand=horizontal.set)
        self.knowledge_tree.bind('<<TreeviewSelect>>', lambda _event: self._select_knowledge())
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.knowledge_detail = tk.Text(right, wrap='word', bg=self.colors['raised'], fg=self.colors['text'],
                                        relief='flat', padx=18, pady=16, width=45, font=('Segoe UI', 10))
        self.knowledge_detail.grid(row=0, column=0, sticky='nsew', padx=(12, 0))
        detail_scroll = ttk.Scrollbar(right, orient='vertical', command=self.knowledge_detail.yview)
        detail_scroll.grid(row=0, column=1, sticky='ns')
        self.knowledge_detail.configure(yscrollcommand=detail_scroll.set)
        footer = ttk.Frame(page, style='Dark.TFrame')
        footer.grid(row=3, column=0, sticky='ew', padx=24, pady=14)
        footer.columnconfigure(0, weight=1)
        self.knowledge_summary = tk.StringVar(value='Selecciona un estado para explorar el conocimiento.')
        ttk.Label(footer, textvariable=self.knowledge_summary, style='Muted.TLabel').grid(row=0, column=0, sticky='w')
        self.knowledge_previous = ttk.Button(footer, text='Anterior', command=lambda: self._page_knowledge(-1))
        self.knowledge_previous.grid(row=0, column=1, padx=6)
        self.knowledge_next = ttk.Button(footer, text='Siguiente', command=lambda: self._page_knowledge(1))
        self.knowledge_next.grid(row=0, column=2)
        self._refresh_knowledge()

    def _reset_knowledge(self) -> None:
        self._knowledge_offset = 0
        self._knowledge_applied_query = self.knowledge_query.get()
        self._knowledge_applied_state = FILTERS[self.knowledge_state.get()]
        self._refresh_knowledge()

    def _page_knowledge(self, direction: int) -> None:
        self._knowledge_offset = max(0, self._knowledge_offset + direction * 100)
        self._refresh_knowledge()

    def _refresh_knowledge(self) -> None:
        if self._knowledge_refreshing:
            return
        criteria = (self._knowledge_applied_state, self._knowledge_applied_query, self._knowledge_offset)
        self._knowledge_refreshing = True
        self.knowledge_summary.set('Comprobando notas y vigencia…')

        def load() -> None:
            try:
                result = self.operations.refresh_knowledge(state=criteria[0], query=criteria[1], offset=criteria[2])
                self._knowledge_results.put((criteria, result))
            except Exception as error:
                self._knowledge_results.put((criteria, error))

        threading.Thread(target=load, name='knowledge-explorer-read', daemon=True).start()
        self.after(50, self._poll_knowledge)

    def _poll_knowledge(self) -> None:
        try:
            criteria, result = self._knowledge_results.get_nowait()
        except queue.Empty:
            self.after(50, self._poll_knowledge)
            return
        self._knowledge_refreshing = False
        if criteria != (self._knowledge_applied_state, self._knowledge_applied_query, self._knowledge_offset):
            self._refresh_knowledge()
            return
        if isinstance(result, Exception):
            self.knowledge_summary.set('No se pudo consultar el conocimiento. Vuelve a buscar.')
            self._knowledge_items = {}
            self._replace_tree(self.knowledge_tree, [])
            self.knowledge_previous.state(['disabled'])
            self.knowledge_next.state(['disabled'])
            self._knowledge_text(str(result))
            return
        snapshot = result
        self._knowledge_offset = snapshot['offset']
        self._knowledge_items = {str(item['claim_id']): item for item in snapshot['items']}
        self._replace_tree(self.knowledge_tree, [
            (key, (STATE_LABELS.get(item['knowledge_state'], item['knowledge_state']), item['title']))
            for key, item in self._knowledge_items.items()
        ], texts={key: item['statement'] for key, item in self._knowledge_items.items()})
        total = snapshot['total']
        self.knowledge_summary.set('No hay afirmaciones para estos filtros. Prueba otro estado o texto.'
                                   if not total else
                                   f"{self._knowledge_offset + 1}–{self._knowledge_offset + len(snapshot['items'])} "
                                   f'de {total} afirmaciones · La vigencia no equivale a verificación factual.')
        self.knowledge_previous.state(['!disabled'] if self._knowledge_offset else ['disabled'])
        self.knowledge_next.state(['!disabled'] if self._knowledge_offset + 100 < total else ['disabled'])
        self._select_knowledge()

    def _select_knowledge(self) -> None:
        selected = self.knowledge_tree.selection()
        if not selected or selected[0] not in self._knowledge_items:
            self._knowledge_detail_id = None
            self._knowledge_text('Selecciona una afirmación para leer su evidencia, procedencia e histórico.')
            return
        item = self._knowledge_items[selected[0]]
        try:
            claim = self.runtime.knowledge_access.claim_payload(item['claim_id'])
            history = self.runtime.knowledge.repository.history(item['claim_id'])
            chain = self.runtime.knowledge.repository.succession(item['claim_id'])
            evidence = '\n\n'.join(entry['quote'] for entry in claim['evidence'])
            sources = '\n'.join(source['title'] + ' · ' + source.get('source_url', 'Documento local')
                                for source in claim['sources'])
            evolution = '\n'.join(f"{entry['created_at']} · {STATE_LABELS[str(entry['to_state'])]} · "
                                   f"{entry['actor']}\n{entry['reason']}" for entry in history)
            succession = '\n'.join(f'{STATE_LABELS[c.knowledge_state]} · {c.statement}' for c in chain)
            self._knowledge_text(
                claim['statement'] + '\n\n' + STATE_LABELS[claim['knowledge_state']]
                + (' · Bloqueo manual' if claim['manual_lock'] else '')
                + ('\nNo disponible como vigente según coherencia/procedencia.'
                   if claim['knowledge_state'] == 'CURRENT' and not item['available_current'] else '')
                + '\n\nEntidades\n' + ', '.join(claim['entities'])
                + '\n\nEvidencia documental\n' + evidence + '\n\nFuentes\n' + sources
                + '\n\nNota\n' + item['title'] + '\n' + item['vault_path']
                + '\n\nEvolución\n' + evolution + '\n\nSucesión\n' + succession
                + '\n\nLa evidencia enlazada puede proceder de un resumen IA. No está verificada independientemente.',
                preserve_scroll=self._knowledge_detail_id == item['claim_id'])
            self._knowledge_detail_id = item['claim_id']
        except (ValueError, LookupError, sqlite3.Error) as error:
            self._knowledge_text('La afirmación cambió o no está disponible. Actualiza la búsqueda.\n' + str(error))

    def _knowledge_text(self, value: str, *, preserve_scroll: bool = False) -> None:
        if self.knowledge_detail.get('1.0', 'end-1c') == value:
            return
        position = self.knowledge_detail.yview()[0] if preserve_scroll else 0
        self.knowledge_detail.configure(state='normal')
        self.knowledge_detail.delete('1.0', 'end')
        self.knowledge_detail.insert('1.0', value)
        self.knowledge_detail.configure(state='disabled')
        self.knowledge_detail.yview_moveto(position)

    def _focus_search(self) -> None:
        if self._current_page == 'knowledge':
            self.knowledge_search_entry.focus_set()
            self.knowledge_search_entry.selection_range(0, 'end')
        else:
            super()._focus_search()
