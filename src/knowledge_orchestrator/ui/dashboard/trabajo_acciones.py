"""Acciones sobre los trabajos: importar, abrir, reintentar e ignorar.

Es la parte del panel que escribe: copia ficheros a la carpeta vigilada y
manda órdenes al runtime. Está separada del pintado precisamente porque es
la que puede romper algo.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from tkinter import filedialog, messagebox

from knowledge_orchestrator.ui.dashboard.trabajo_detalle import DetalleMixin


class AccionesMixin(DetalleMixin):
    """Todo lo que el panel hace además de mirar."""

    def _import_documents(self) -> None:
        selected = filedialog.askopenfilenames(
            parent=self, title="Importar documentos", filetypes=(("Documentos Markdown", "*.md"),)
        )
        if not selected:
            return
        self.runtime.paths.inbox.mkdir(parents=True, exist_ok=True)
        imported = 0
        failures: list[str] = []
        for raw_path in selected:
            source = Path(raw_path)
            try:
                target = self._available_inbox_path(source.name)
                if source.resolve() != target.resolve():
                    shutil.copy2(source, target)
                if self.runtime.worker.submit(target):
                    imported += 1
            except OSError as error:
                failures.append(f"{source.name}: {error}")
        if failures:
            messagebox.showerror("Algunos documentos no se importaron", "\n".join(failures[:6]), parent=self)
        plural = "s" if imported != 1 else ""
        self.status_var.set(f"{imported} documento{plural} añadido{plural} a la carpeta vigilada.")
        self._show_page("work")
        self._work_filter = "active"
        self.after(250, lambda: self._refresh(force=True))

    def _available_inbox_path(self, filename: str) -> Path:
        candidate = self.runtime.paths.inbox / filename
        if not candidate.exists():
            return candidate
        stem, suffix = candidate.stem, candidate.suffix
        index = 2
        while True:
            alternative = candidate.with_name(f"{stem} ({index}){suffix}")
            if not alternative.exists():
                return alternative
            index += 1

    def _open_inbox(self) -> None:
        self.runtime.paths.inbox.mkdir(parents=True, exist_ok=True)
        self._open_path(self.runtime.paths.inbox)

    def _open_selected_location(self) -> None:
        item = self._selected_item()
        if not item or not item.path:
            return
        path = Path(item.path)
        target = path if path.is_dir() else path.parent
        if not target.exists():
            messagebox.showinfo("Ubicación no disponible", "El archivo ya no está en esa ubicación.", parent=self)
            return
        self._open_path(target)

    def _open_path(self, path: Path) -> None:
        try:
            os.startfile(str(path))
        except OSError as error:
            messagebox.showerror("No se pudo abrir la ubicación", str(error), parent=self)

    def _retry_selected(self) -> None:
        item = self._selected_item()
        if not item:
            return
        if item.incident_id is not None:
            path = Path(item.path)
            if not path.exists():
                messagebox.showinfo(
                    "El archivo ya no está disponible",
                    "Vuelve a importarlo o cópialo de nuevo a la carpeta vigilada.",
                    parent=self,
                )
                return
            changed = self.runtime.worker.retry(path)
        elif item.task_id:
            changed = self.runtime.workflow_repository.retry_failed_task(item.task_id)
        else:
            changed = False
        if changed:
            self.status_var.set(f"Reintento solicitado para {item.title}.")
            self._work_filter = "active"
            self._refresh(force=True)
        else:
            messagebox.showinfo(
                "El estado cambió", "La tarea ya no está fallida. La lista se actualizará.", parent=self
            )
            self._refresh(force=True)

    def _cancel_or_ignore_selected(self) -> None:
        item = self._selected_item()
        if not item:
            return
        if item.category == "active" and item.task_id:
            if not messagebox.askyesno("Cancelar tarea", "La tarea dejará de ejecutarse. ¿Continuar?", parent=self):
                return
            changed = self.runtime.broker_worker.request_cancel(item.task_id)
            message = "Cancelación solicitada." if changed else "La tarea ya cambió de estado."
        else:
            if not messagebox.askyesno(
                "Ignorar incidencia",
                "El trabajo se marcará como cancelado, pero se conservarán el archivo y el historial. ¿Continuar?",
                parent=self,
            ):
                return
            changed = (
                self.runtime.repository.ignore_ingestion_incident(item.incident_id)
                if item.incident_id is not None
                else self.runtime.workflow_repository.ignore_failed_capture(item.capture_id)
            )
            message = "Incidencia cerrada; el historial se conserva." if changed else "El trabajo ya cambió de estado."
        self.status_var.set(message)
        self._refresh(force=True)
