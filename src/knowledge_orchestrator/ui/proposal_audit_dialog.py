"""THESIS: recorrer versiones, evidencia y decisiones de una propuesta sin consultar SQL.
OWN-WORLD: extensión de Revisión, grafito/cian y controles ttk existentes.
STORY: elegir versión, comparar, identificar análisis y consultar la decisión registrada.
FIRST VIEWPORT: identidad fija y versiones arriba; comparación flexible; cerrar al pie.
FORM: diálogo de consulta con pestañas y lectura en segundo plano, sin acciones de publicación.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk

from knowledge_orchestrator.ui.automation_plan import text_panel, write_text
from knowledge_orchestrator.ui.proposal_audit_presenter import audit_text


class ProposalAuditDialog(tk.Toplevel):
    evidence: tk.Text
    decision: tk.Text

    def __init__(self, parent, reader, candidate_id: int) -> None:
        super().__init__(parent)
        self.reader, self.candidate_id = reader, candidate_id
        self.busy = self.closed = False
        self.record: dict | None = None
        self.pending: tuple[int, int | None] = (0, None)
        self.results: queue.SimpleQueue = queue.SimpleQueue()
        self._poll_id = None
        self.title(f'Trazabilidad · propuesta {candidate_id}')
        self.geometry('1000x680')
        self.minsize(800, 540)
        self.transient(parent)
        self.configure(bg=parent.colors['surface'])
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.status = tk.StringVar(value=f'Leyendo propuesta {candidate_id}…')
        ttk.Label(self, textvariable=self.status, wraplength=740, justify='left').grid(
            row=0, column=0, sticky='ew', padx=16, pady=12)
        controls = ttk.Frame(self)
        controls.grid(row=1, column=0, sticky='ew', padx=16, pady=(0, 8))
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text='Versión de propuesta').grid(row=0, column=0, padx=(0, 8))
        self.choice = ttk.Combobox(controls, state='disabled')
        self.choice.grid(row=0, column=1, sticky='ew')
        self.choice.bind('<<ComboboxSelected>>', self._choose)
        self.previous = ttk.Button(controls, text='Más recientes', command=lambda: self._page(-100))
        self.previous.grid(row=0, column=2, padx=4)
        self.next = ttk.Button(controls, text='Más antiguas', command=lambda: self._page(100))
        self.next.grid(row=0, column=3)
        tabs = ttk.Notebook(self)
        tabs.grid(row=2, column=0, sticky='nsew', padx=16)
        comparison = ttk.Panedwindow(tabs, orient='horizontal')
        tabs.add(comparison, text='Comparación')
        widgets = []
        for label in ('Antes', 'Propuesto en esta revisión'):
            outer = ttk.Frame(comparison, padding=8)
            outer.columnconfigure(0, weight=1)
            outer.rowconfigure(1, weight=1)
            ttk.Label(outer, text=label).grid(row=0, column=0, sticky='w', pady=(0, 8))
            frame, widget = text_panel(outer, parent.colors)
            frame.grid(row=1, column=0, sticky='nsew')
            comparison.add(outer, weight=1)
            widgets.append(widget)
        self.before, self.proposed = widgets
        for name, label in (('evidence', 'Evidencia y análisis'), ('decision', 'Decisión y publicación')):
            frame, widget = text_panel(tabs, parent.colors)
            tabs.add(frame, text=label)
            setattr(self, name, widget)
        footer = ttk.Frame(self)
        footer.grid(row=3, column=0, sticky='ew', padx=16, pady=12)
        self.retry = ttk.Button(footer, text='Actualizar consulta', command=lambda: self._load(*self.pending))
        self.retry.pack(side='left')
        self.close_button = ttk.Button(footer, text='Cerrar', command=self.destroy)
        self.close_button.pack(side='right')
        self.bind('<Escape>', lambda _event: self.destroy())
        self.bind('<Destroy>', self._destroyed, add='+')
        for widget in (self.before, self.proposed, self.evidence, self.decision):
            write_text(widget, 'Leyendo el registro…')
        self._poll_id = self.after(100, self._poll)
        self._load(0, None)

    @staticmethod
    def _label(version):
        return f"Revisión {version['revision']} · {version['created_at']} · {version['actor']}"

    def _actions(self):
        self.retry.state(['disabled'] if self.busy else ['!disabled'])
        available = self.record is not None and not self.busy
        self.choice.configure(state='readonly' if available and self.record['versions'] else 'disabled')
        self.previous.state(['!disabled'] if available and self.record['offset'] > 0 else ['disabled'])
        self.next.state(['!disabled'] if available and self.record['offset'] + 100 < self.record['total']
                        else ['disabled'])

    def _load(self, offset: int, revision: int | None):
        if self.busy or self.closed:
            return
        self.busy = True
        self.pending = (offset, revision)
        self.status.set(f'Leyendo propuesta {self.candidate_id}… '
                        'El contenido visible corresponde a la última consulta.')
        self._actions()
        reader, candidate_id, results = self.reader, self.candidate_id, self.results
        def read():
            try:
                results.put((reader.read(candidate_id, offset=offset, revision=revision), None))
            except Exception:
                results.put((None, 'No se pudo leer esta consulta. '
                                  'Se conserva el registro anterior; pulsa Reintentar.'))
        threading.Thread(target=read, name='proposal-audit-read', daemon=True).start()

    def _choose(self, _event=None):
        index = self.choice.current()
        if not self.record:
            return
        selected = self.record['selected']
        self.choice.set(self._label(selected) if selected else 'Sin revisiones')
        if not self.busy and 0 <= index < len(self.record['versions']):
            self._load(self.record['offset'], self.record['versions'][index]['revision'])

    def _page(self, delta):
        if not self.busy and self.record:
            self._load(max(0, self.record['offset'] + delta), None)

    def _poll(self):
        if self.closed:
            return
        try:
            value, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            if error:
                self.status.set(error)
                self.retry.configure(text='Reintentar')
            else:
                self.record = value
                selected = value['selected']
                self.pending = (value['offset'], selected['revision'] if selected else None)
                self.choice.configure(values=[self._label(version) for version in value['versions']])
                self.choice.set(self._label(selected) if selected else 'Sin revisiones')
                texts = audit_text(value)
                self.status.set(texts['summary'])
                for name in ('before', 'proposed', 'evidence', 'decision'):
                    write_text(getattr(self, name), texts[name])
                self.retry.configure(text='Actualizar consulta')
            self._actions()
        self._poll_id = self.after(150, self._poll)

    def _destroyed(self, event):
        if event.widget == self:
            self.closed = True
            if self._poll_id:
                self.after_cancel(self._poll_id)
