"""Formulario nativo con selección de fuentes preservada entre páginas."""
from __future__ import annotations

import tkinter as tk
from dataclasses import asdict
from tkinter import ttk

from knowledge_orchestrator.domain.automation import AutomationPolicyConfig
from knowledge_orchestrator.ui.automation_presenter import CHOICES, NUMERIC_FIELDS, config_from_fields


class AutomationForm(ttk.Frame):
    def __init__(self, parent, colors: dict, changed, page_sources) -> None:
        super().__init__(parent)
        self.changed, self._rendering = changed, False
        self.source_ids: set[int] = set()
        self._source_rows: set[int] = set()
        self.fields: dict[str, tk.StringVar] = {}
        self.choices: dict[str, dict[str, tk.BooleanVar]] = {}
        self.inputs: list = []
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=colors['surface'], highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=scroll.set)
        content = ttk.Frame(self.canvas, padding=12)
        window = self.canvas.create_window((0, 0), anchor='nw', window=content)
        content.columnconfigure(1, weight=1)
        content.bind('<Configure>', lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(window, width=event.width))
        row = 0
        labels = {'name': 'Nombre de la política', 'claim_types': 'Tipos de afirmación (separados por comas)',
                   **NUMERIC_FIELDS}
        for field, label in labels.items():
            ttk.Label(content, text=label, wraplength=260).grid(row=row, column=0, sticky='w', padx=(0, 16), pady=5)
            variable = self.fields[field] = tk.StringVar()
            variable.trace_add('write', self._edited)
            entry = ttk.Entry(content, textvariable=variable)
            entry.grid(row=row, column=1, sticky='ew', pady=5)
            self.inputs.append(entry)
            row += 1
        titles = {'source_kinds': 'Conectores permitidos', 'source_roles': 'Procedencia permitida',
                   'relations': 'Cambios permitidos'}
        for field, choices in CHOICES.items():
            ttk.Label(content, text=titles[field]).grid(row=row, column=0, sticky='nw', pady=(12, 4))
            group = ttk.Frame(content)
            group.grid(row=row, column=1, sticky='ew', pady=(12, 4))
            self.choices[field] = {}
            for index, (value, label) in enumerate(choices.items()):
                option = self.choices[field][value] = tk.BooleanVar()
                check = ttk.Checkbutton(group, text=label, variable=option, command=self._edited)
                check.grid(row=index, column=0, sticky='w', pady=2)
                self.inputs.append(check)
            row += 1
        ttk.Label(content, text='Fuentes autorizadas · selecciona con Ctrl o Mayús', wraplength=650).grid(
            row=row, column=0, columnspan=2, sticky='w', pady=(16, 6))
        self.sources = ttk.Treeview(content, columns=('source', 'trust', 'enabled'), show='headings',
                                    selectmode='extended', height=6, style='Dark.Treeview')
        for name, label, width in [('source', 'Fuente', 360), ('trust', 'Confianza', 90),
                                    ('enabled', 'Vigilancia', 100)]:
            self.sources.heading(name, text=label)
            self.sources.column(name, width=width, minwidth=60)
        self.sources.grid(row=row + 1, column=0, columnspan=2, sticky='ew')
        self.sources.bind('<<TreeviewSelect>>', self._source_selection)
        self.inputs.append(self.sources)
        source_scroll = ttk.Scrollbar(content, orient='vertical', command=self.sources.yview)
        source_scroll.grid(row=row + 1, column=2, sticky='ns')
        self.sources.configure(yscrollcommand=source_scroll.set)
        bar = ttk.Frame(content)
        bar.grid(row=row + 2, column=0, columnspan=2, sticky='ew', pady=8)
        self.source_status = tk.StringVar(value='Cargando fuentes…')
        ttk.Label(bar, textvariable=self.source_status).pack(side='left')
        self.previous = ttk.Button(bar, text='Anteriores', command=lambda: page_sources(-100))
        self.previous.pack(side='right', padx=4)
        self.next = ttk.Button(bar, text='Siguientes', command=lambda: page_sources(100))
        self.next.pack(side='right', padx=4)
        ttk.Label(content, text='Guardar crea una versión desactivada. '
                  'Ninguna política puede ignorar bloqueos manuales, '
                  'contradicciones, evidencia o cambios externos en una nota.', wraplength=650).grid(
                      row=row + 3, column=0, columnspan=2, sticky='ew', pady=(8, 12))
        self._bind_scroll(content)

    def _bind_scroll(self, widget):
        if not isinstance(widget, (ttk.Treeview, ttk.Combobox, ttk.Scrollbar)):
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

    def _edited(self, *_args):
        if not self._rendering:
            self.changed()

    def _source_selection(self, _event=None):
        if self._rendering or self.sources.instate(['disabled']):
            return
        chosen = {int(value) for value in self.sources.selection()}
        updated = (self.source_ids - self._source_rows) | chosen
        if updated != self.source_ids:
            self.source_ids = updated
            self.changed()
        self._source_status()

    def _source_status(self):
        self.source_status.set(f'{len(self.source_ids)} seleccionadas · {len(self._source_rows)} en esta página')

    def show_sources(self, rows: list[dict], offset: int):
        self._rendering = True
        self.sources.delete(*self.sources.get_children())
        self._source_rows = {row['source_id'] for row in rows}
        for row in rows:
            config = row['config']
            self.sources.insert('', 'end', iid=str(row['source_id']), values=(
                config['name'], config['trust_level'], 'Activa' if config['enabled'] else 'Desactivada'))
        self.sources.selection_set([str(value) for value in self.source_ids & self._source_rows])
        self._rendering = False
        self._source_status()
        self.previous.state(['!disabled'] if offset else ['disabled'])
        self.next.state(['!disabled'] if len(rows) == 100 else ['disabled'])

    def set_config(self, config: dict | None):
        self._rendering = True
        values = config or {**asdict(AutomationPolicyConfig('Nueva política', (1,))), 'source_ids': []}
        for name, variable in self.fields.items():
            variable.set(', '.join(values[name]) if name == 'claim_types' else str(values[name]))
        for name, choices in self.choices.items():
            for value, option in choices.items():
                option.set(value in values[name])
        self.source_ids = set(values['source_ids'])
        self.sources.selection_set([str(value) for value in self.source_ids & self._source_rows])
        self._source_status()
        self._rendering = False

    def read_config(self) -> AutomationPolicyConfig:
        return config_from_fields({name: variable.get() for name, variable in self.fields.items()},
                                  {name: [value for value, variable in options.items() if variable.get()]
                                   for name, options in self.choices.items()}, self.source_ids)

    def enable(self, enabled: bool):
        for widget in self.inputs:
            widget.state(['!disabled'] if enabled else ['disabled'])
