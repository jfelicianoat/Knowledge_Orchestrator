"""Comparación de un plan simulado con evidencia legible y sin controles de publicación."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from knowledge_orchestrator.ui.automation_presenter import reasons


def write_text(widget, value: str) -> None:
    if len(value) > 200000:
        value = value[:200000] + '\n\nVista abreviada por tamaño; consulta el documento completo en Conocimiento.'
    widget.configure(state='normal')
    widget.delete('1.0', 'end')
    widget.insert('1.0', value)
    widget.configure(state='disabled')


def text_panel(parent, colors: dict, *, height: int = 8):
    frame = ttk.Frame(parent)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    widget = tk.Text(frame, wrap='word', bg=colors['raised'], fg=colors['text'], height=height,
                     padx=10, pady=8, relief='flat', state='disabled', width=30)
    widget.grid(row=0, column=0, sticky='nsew')
    scroll = ttk.Scrollbar(frame, orient='vertical', command=widget.yview)
    scroll.grid(row=0, column=1, sticky='ns')
    widget.configure(yscrollcommand=scroll.set)
    return frame, widget


class AutomationPlanView(ttk.Frame):
    def __init__(self, parent, colors: dict) -> None:
        super().__init__(parent, padding=8)
        self.items: dict[str, dict] = {}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, bg=colors['surface'], highlightthickness=0, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        outer_scroll = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        outer_scroll.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=outer_scroll.set)
        body = ttk.Frame(self.canvas)
        body.columnconfigure(0, weight=1)
        # The comparison needs 220 pixels in addition to its vertical margins.
        body.rowconfigure(2, weight=1, minsize=220 + 16)
        window = self.canvas.create_window((0, 0), anchor='nw', window=body)
        body.bind('<Configure>', lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(
            window, width=event.width, height=max(body.winfo_reqheight(), event.height)))
        options = ttk.Frame(body)
        options.grid(row=0, column=0, sticky='ew')
        ttk.Label(options, text='Propuestas por página (1–100)').pack(side='left')
        self.page_size = tk.StringVar(value='100')
        ttk.Spinbox(options, from_=1, to=100, textvariable=self.page_size, width=5).pack(side='left', padx=8)
        self.summary = tk.StringVar(value='Guarda la configuración y pulsa «Simular guardada». '
                                    'No se publicarán cambios.')
        ttk.Label(options, textvariable=self.summary, wraplength=570, justify='left').pack(side='left', padx=8)
        self.tree = ttk.Treeview(body, columns=('proposal', 'eligible', 'reason'), show='headings', height=4,
                                 selectmode='browse', style='Dark.Treeview')
        for name, title, width in [('proposal', 'Propuesta', 240), ('eligible', 'Evaluación', 110),
                                    ('reason', 'Condiciones', 410)]:
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, minwidth=70)
        self.tree.grid(row=1, column=0, sticky='ew')
        scroll = ttk.Scrollbar(body, orient='vertical', command=self.tree.yview)
        scroll.grid(row=1, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>', lambda _event: self.detail())
        panes = ttk.Panedwindow(body, orient='horizontal')
        panes.grid(row=2, column=0, sticky='nsew', pady=8)
        widgets = []
        for title in ('Antes', 'Propuesto · conserva histórico'):
            outer = ttk.Frame(panes)
            outer.columnconfigure(0, weight=1)
            outer.rowconfigure(1, weight=1)
            ttk.Label(outer, text=title).grid(row=0, column=0, sticky='w', pady=4)
            frame, widget = text_panel(outer, colors)
            frame.grid(row=1, column=0, sticky='nsew')
            panes.add(outer, weight=1)
            widgets.append(widget)
        self.before, self.proposed = widgets
        frame, self.evidence = text_panel(body, colors, height=5)
        frame.grid(row=3, column=0, sticky='ew')
        self._bind_scroll(body)

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

    def render(self, simulation: dict | None) -> None:
        self.tree.delete(*self.tree.get_children())
        self.items = {}
        if simulation:
            plan = simulation['plan']
            counts = plan['counts']
            self.summary.set(f"Política {simulation['policy_id']} · versión {simulation['policy_revision']} · "
                             f"{counts['eligible']} de {counts['tasks']} propuestas elegibles · "
                             f"Cupo disponible hoy: {plan['daily_remaining']}. "
                             + reasons(plan['execution_gates']) + ' La simulación no publica cambios.')
            for item in plan['items']:
                identifier = str(item['candidate_id'])
                self.items[identifier] = item
                self.tree.insert('', 'end', iid=identifier, values=(
                    f"{item.get('title', 'Propuesta')} · {identifier} · revisión {item['revision']}",
                    'Elegible' if item['eligible'] else 'Revisión necesaria',
                    reasons(item['blockers']) or 'Cumple las condiciones; se comprobará de nuevo al aplicar.'))
        else:
            self.summary.set('Guarda la configuración y pulsa «Simular guardada». No se publicarán cambios.')
        self.detail()

    def detail(self):
        selected = self.tree.selection()
        item = self.items.get(selected[0]) if selected else None
        if item is None:
            for widget in (self.before, self.proposed, self.evidence):
                write_text(widget, 'Selecciona una propuesta para comparar el cambio y su evidencia.')
            return
        assessment = item.get('assessment') or {}
        from knowledge_orchestrator.ui.dashboard.revision import RISK_LABELS
        evidence = [assessment.get('rationale', ''), reasons(item['blockers'])]
        evidence.extend(RISK_LABELS.get(risk, 'Requiere revisión de la evidencia.')
                        for risk in assessment.get('risks', []))
        for entry in assessment.get('evidence', []):
            source = entry['source']
            evidence.append(f"{source['title']} · {source.get('source_url', '')}\n{entry['quote']}")
        write_text(self.before, item.get('before', 'No hay una versión aplicable en esta propuesta.'))
        write_text(self.proposed, item.get('proposed', 'La nota se conserva sin cambios.'))
        write_text(self.evidence, '\n\n'.join(value for value in evidence if value))
