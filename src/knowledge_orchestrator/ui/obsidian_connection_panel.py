"""Ajustes del puente; la comprobación de red ocurre fuera del hilo Tk."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import ttk

from knowledge_orchestrator.integrations.obsidian_bridge import ObsidianBridgeConflict, ObsidianBridgeUnavailable
from knowledge_orchestrator.services.obsidian_connection import ObsidianConnection


class ObsidianConnectionPanel(ttk.LabelFrame):
    def __init__(self, parent, connection: ObsidianConnection) -> None:
        super().__init__(parent, text='Edición segura en Obsidian', padding=14)
        self.connection = connection
        self.results: queue.SimpleQueue = queue.SimpleQueue()
        self.closed = self.busy = False
        self.columnconfigure(1, weight=1)
        self.url = tk.StringVar(value=connection.configured_url())
        self.token = tk.StringVar(value='')
        self.status = tk.StringVar(value='Abre la bóveda local en Obsidian y activa el complemento '
                                  'Knowledge Orchestrator Bridge. Usa una clave distinta a la del Broker.')
        for row, (label, variable) in enumerate((('Dirección local', self.url), ('Clave del puente', self.token))):
            ttk.Label(self, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=4)
            entry = ttk.Entry(self, textvariable=variable, show='●' if row else '')
            entry.grid(row=row, column=1, sticky='ew', pady=4)
        self.save_button = ttk.Button(self, text='Guardar conexión', command=lambda: self._run(save=True))
        self.save_button.grid(row=0, column=2, padx=10)
        self.check_button = ttk.Button(self, text='Comprobar conexión', command=lambda: self._run(save=False))
        self.check_button.grid(row=1, column=2, padx=10)
        ttk.Label(self, text='Deja la clave vacía para conservar la guardada. Se protege para tu usuario de Windows.',
                  wraplength=950).grid(row=2, column=0, columnspan=3, sticky='w', pady=5)
        ttk.Label(self, textvariable=self.status, wraplength=950, justify='left').grid(
            row=3, column=0, columnspan=3, sticky='ew', pady=5)
        self.bind('<Destroy>', self._destroyed, add='+')
        self.poll_id = self.after(100, self._poll)

    def _run(self, *, save: bool) -> None:
        if self.closed or self.busy:
            return
        self.busy = True
        self.save_button.state(['disabled'])
        self.check_button.state(['disabled'])
        connection, results = self.connection, self.results
        url, token = self.url.get(), self.token.get() or None
        if save:
            self.token.set('')
        self.status.set('Guardando conexión…' if save else 'Comprobando la conexión guardada…')

        def work():
            try:
                if save:
                    connection.save(url, token=token)
                    message = 'Conexión guardada. Compruébala con Obsidian abierto. Las operaciones pendientes '
                    message += 'se recuperan al reiniciar el Orchestrator con el puente disponible.'
                else:
                    connection.status()
                    message = ('Obsidian responde y corresponde a la bóveda configurada. '
                               'No se ha modificado ninguna nota.')
            except (ObsidianBridgeUnavailable, ObsidianBridgeConflict) as error:
                message = str(error)
            except Exception:
                message = 'No se pudo completar la operación. Revisa los ajustes del puente en Obsidian.'
            results.put(message)

        threading.Thread(target=work, name='obsidian-connection', daemon=True).start()

    def _poll(self) -> None:
        if self.closed:
            return
        try:
            self.status.set(self.results.get_nowait())
            self.busy = False
            self.save_button.state(['!disabled'])
            self.check_button.state(['!disabled'])
        except queue.Empty:
            pass
        self.poll_id = self.after(100, self._poll)

    def _destroyed(self, event) -> None:
        if event.widget is self:
            self.closed = True
            self.after_cancel(self.poll_id)
