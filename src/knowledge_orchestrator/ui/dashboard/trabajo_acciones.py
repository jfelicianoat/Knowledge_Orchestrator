"""Acciones sobre los trabajos: importar, abrir, reintentar e ignorar.

Es la parte del panel que escribe: copia ficheros a la carpeta vigilada y
manda órdenes al runtime. Está separada del pintado precisamente porque es
la que puede romper algo.
"""
from __future__ import annotations

import os
import queue
import shutil
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from knowledge_orchestrator.domain.errors import CaptureContractError
from knowledge_orchestrator.services.markdown_import import ImportCandidate, inspect_import, write_converted
from knowledge_orchestrator.ui.dashboard.estilo import FONT, FONT_SEMIBOLD
from knowledge_orchestrator.ui.dashboard.trabajo_detalle import DetalleMixin


def _size_label(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB".replace(".", ",")
    return f"{size / (1024 * 1024):.1f} MB".replace(".", ",")


class AccionesMixin(DetalleMixin):
    """Todo lo que el panel hace además de mirar."""

    def _import_documents(self) -> None:
        """Añade documentos elegidos por la persona, convirtiendo los que no son capturas.

        Antes se copiaba cada fichero tal cual, en el hilo de Tk, y un Markdown
        normal terminaba en cuarentena por no llevar el contrato del plugin.
        Ahora se inspecciona primero (fuera del hilo de la interfaz), se explica
        por qué no entra lo que parece una captura rota y se ofrece convertir el
        resto. El original nunca se modifica.
        """

        selected = filedialog.askopenfilenames(
            parent=self, title="Importar documentos",
            filetypes=(("Documentos de texto", "*.md *.markdown *.txt"), ("Markdown", "*.md"), ("Texto", "*.txt")),
        )
        if not selected:
            return
        paths = [Path(raw_path) for raw_path in selected]
        plural = "s" if len(paths) != 1 else ""
        self.status_var.set(f"Revisando {len(paths)} documento{plural}…")
        self._run_import_step(lambda: [inspect_import(path) for path in paths], self._review_import_candidates)

    def _run_import_step(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        """Ejecuta lectura y copia fuera del hilo de Tk y vuelve a él con el resultado."""

        results: queue.Queue[tuple[Any, BaseException | None]] = queue.Queue(maxsize=1)

        def run() -> None:
            try:
                results.put((work(), None))
            except Exception as error:  # noqa: BLE001 - se enseña a la persona, no se pierde
                results.put((None, error))

        def poll() -> None:
            try:
                value, error = results.get_nowait()
            except queue.Empty:
                self.after(50, poll)
                return
            if error is not None:
                messagebox.showerror("No se pudo importar", str(error) or type(error).__name__, parent=self)
                self.status_var.set("La importación no se completó.")
                return
            done(value)

        threading.Thread(target=run, name="document-import", daemon=True).start()
        self.after(50, poll)

    def _review_import_candidates(self, candidates: list[ImportCandidate]) -> None:
        problems = [item for item in candidates if item.kind in {"malformed", "unreadable"}]
        compatible = [item for item in candidates if item.kind == "compatible"]
        ordinary = [item for item in candidates if item.kind == "ordinary"]
        if problems:
            lines = []
            for item in problems[:8]:
                prefix = "parece una captura, pero " if item.kind == "malformed" else ""
                lines.append(f"• {item.path.name}: {prefix}{item.reason}")
            if len(problems) > 8:
                lines.append(f"… y {len(problems) - 8} más")
            messagebox.showwarning(
                "Algunos documentos no se añadieron",
                "\n".join(lines) + "\n\nCorrige el fichero y vuelve a importarlo; el original no se ha tocado.",
                parent=self,
            )
        if ordinary and not self._confirm_conversion(ordinary):
            ordinary = []
        if not compatible and not ordinary:
            self.status_var.set("No se añadió ningún documento.")
            return
        self.status_var.set("Añadiendo documentos a la carpeta vigilada…")
        self._run_import_step(lambda: self._deliver_imports(compatible, ordinary), self._finish_import)

    def _confirm_conversion(self, ordinary: list[ImportCandidate]) -> bool:
        """Un único diálogo para todos los documentos que hay que convertir."""

        c = self.colors
        dialog = tk.Toplevel(self)
        dialog.title("Convertir documentos")
        dialog.transient(self)
        dialog.configure(background=c["surface"])
        dialog.resizable(False, False)
        plural = "s no son capturas" if len(ordinary) != 1 else " no es una captura"
        tk.Label(
            dialog, bg=c["surface"], fg=c["text"], font=(FONT_SEMIBOLD, 11), anchor="w", justify="left",
            text=f"{len(ordinary)} documento{plural} del plugin.",
        ).pack(fill="x", padx=20, pady=(18, 4))
        tk.Label(
            dialog, bg=c["surface"], fg=c["muted"], font=(FONT, 9), anchor="w", justify="left", wraplength=520,
            text="Se creará una captura nueva con su texto completo como contenido. "
                 "El archivo original no se modifica.",
        ).pack(fill="x", padx=20, pady=(0, 10))
        listing = tk.Frame(dialog, bg=c["raised"])
        listing.pack(fill="x", padx=20)
        for item in ordinary[:8]:
            tk.Label(
                listing, bg=c["raised"], fg=c["text"], font=(FONT, 9), anchor="w", justify="left",
                wraplength=500, text=f"«{item.title}» · {item.path.name} · {_size_label(item.size_bytes)}",
            ).pack(fill="x", padx=12, pady=3)
        if len(ordinary) > 8:
            tk.Label(listing, bg=c["raised"], fg=c["muted"], font=(FONT, 9), anchor="w",
                     text=f"… y {len(ordinary) - 8} más").pack(fill="x", padx=12, pady=3)
        answer = {"convert": False}

        def accept() -> None:
            answer["convert"] = True
            dialog.destroy()

        actions = tk.Frame(dialog, bg=c["surface"])
        actions.pack(fill="x", padx=20, pady=16)
        ttk.Button(actions, text="Cancelar", style="Secondary.TButton", command=dialog.destroy).pack(side="right")
        ttk.Button(actions, text="Convertir y añadir", style="Accent.TButton", command=accept).pack(
            side="right", padx=(0, 8))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.grab_set()
        self.wait_window(dialog)
        return answer["convert"]

    def _deliver_imports(
        self, compatible: list[ImportCandidate], ordinary: list[ImportCandidate],
    ) -> tuple[list[Path], list[str]]:
        """Copia y conversión, en segundo plano: solo toca disco, nunca widgets."""

        inbox = self.runtime.paths.inbox
        inbox.mkdir(parents=True, exist_ok=True)
        targets: list[Path] = []
        failures: list[str] = []
        for item in compatible:
            try:
                target = self._available_inbox_path(item.path.name)
                if item.path.resolve() != target.resolve():
                    shutil.copy2(item.path, target)
                targets.append(target)
            except OSError as error:
                failures.append(f"{item.path.name}: {error}")
        for item in ordinary:
            try:
                targets.append(write_converted(item.path, inbox))
            except (OSError, ValueError, CaptureContractError) as error:
                failures.append(f"{item.path.name}: {error}")
        return targets, failures

    def _finish_import(self, outcome: tuple[list[Path], list[str]]) -> None:
        targets, failures = outcome
        imported = sum(1 for target in targets if self.runtime.worker.submit(target))
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
        single = self._selected_item()
        if single is not None and len(self._selected_items()) == 1:
            if single.status == "AWAITING_REVIEW":
                self._open_draft_review(single.capture_id)
                return
            if single.status == "DRAFT_REJECTED":
                self._reprocess_rejected_draft(single.capture_id)
                return
        items = tuple(item for item in self._selected_items() if self._can_send_item(item))
        if not items:
            return

        sent = 0
        task_ids: list[str] = []
        failures: list[str] = []
        for item in items:
            try:
                if item.task_id and item.status == "READY":
                    changed = True
                elif item.incident_id is not None:
                    path = Path(item.path)
                    if not path.exists():
                        failures.append(f"{item.title}: el archivo ya no está disponible")
                        continue
                    changed = self.runtime.worker.retry(path)
                elif item.task_id:
                    changed = self.runtime.workflow_repository.retry_failed_task(item.task_id)
                else:
                    changed = self.runtime.workflow_repository.reopen_failed_capture(item.capture_id)
            except OSError as error:
                failures.append(f"{item.title}: {error}")
            else:
                sent += int(changed)
                if changed and item.task_id:
                    task_ids.append(item.task_id)
                if not changed:
                    failures.append(f"{item.title}: el estado cambió antes del envío")

        if task_ids:
            self.runtime.broker_worker.request_dispatch(task_ids)
        if failures:
            messagebox.showwarning(
                "Algunos documentos no se enviaron",
                "\n".join(failures[:6]),
                parent=self,
            )
        if sent:
            plural = "s" if sent != 1 else ""
            self.status_var.set(f"{sent} documento{plural} puesto{plural} de nuevo en la cola de envío.")
            self._work_filter = "active"
        else:
            self.status_var.set("No se pudo reenviar ningún documento seleccionado.")
        self._selected_work_id = None
        self._selected_work_ids = ()
        self._refresh(force=True)

    def _cancel_or_ignore_selected(self) -> None:
        item = self._selected_item()
        if not item:
            return
        if item.status == "AWAITING_REVIEW":
            draft = self.runtime.publication_repository.get_draft(item.capture_id)
            if draft is None or not messagebox.askyesno(
                "Descartar borrador",
                "No se publicará. La fuente y el resultado se conservan y podrás volver a procesarlo. ¿Continuar?",
                parent=self,
            ):
                return
            changed = self.runtime.publication_repository.reject_draft(draft.workflow_id)
            message = "Borrador descartado; se conservan la fuente y el resultado." if changed \
                else "El borrador ya se decidió desde otro sitio."
        elif self._can_cancel_item(item):
            if not messagebox.askyesno(
                "Cancelar procesamiento",
                "Se detendrá el documento entero: no se enviarán más partes y se pedirá al Broker que pare las "
                "que ya tiene. El original se conserva. ¿Continuar?",
                parent=self,
            ):
                return
            changed = self.runtime.broker_worker.request_cancel_capture(item.capture_id)
            message = (
                "Documento cancelado; el original se conserva." if changed
                else "El documento ya terminó o cambió de estado."
            )
        else:
            if not messagebox.askyesno(
                "Ignorar incidencia",
                "El documento se marcará como cancelado, pero se conservarán el archivo y el historial. ¿Continuar?",
                parent=self,
            ):
                return
            changed = (
                self.runtime.repository.ignore_ingestion_incident(item.incident_id)
                if item.incident_id is not None
                else self.runtime.workflow_repository.ignore_failed_capture(item.capture_id)
            )
            message = (
                "Incidencia cerrada; el historial se conserva."
                if changed
                else "El documento ya cambió de estado."
            )
        self.status_var.set(message)
        self._refresh(force=True)

    # ------------------------------------------------------ borradores (H01)

    def _open_draft_review(self, capture_id: str) -> None:
        from knowledge_orchestrator.ui.draft_review_dialog import DraftReviewDialog

        draft = self.runtime.publication_repository.get_draft(capture_id)
        if draft is None:
            self.status_var.set("El borrador ya no está pendiente.")
            self._refresh(force=True)
            return

        def done(message: str) -> None:
            self.status_var.set(message)
            self._refresh(force=True)

        self._draft_dialog = DraftReviewDialog(
            self, draft,
            approve=self.runtime.publication_repository.approve_draft,
            reject=self.runtime.publication_repository.reject_draft,
            on_done=done,
        )

    def _reprocess_rejected_draft(self, capture_id: str) -> None:
        if not messagebox.askyesno(
            "Volver a procesar",
            "Se generará un borrador nuevo con la configuración actual del perfil. El descartado se conserva. "
            "¿Continuar?",
            parent=self,
        ):
            return
        changed = self.runtime.publication_repository.reopen_rejected_draft(capture_id)
        self.status_var.set(
            "Documento en cola para procesarse de nuevo." if changed else "El documento ya cambió de estado."
        )
        if changed:
            self._work_filter = "active"
        self._refresh(force=True)
