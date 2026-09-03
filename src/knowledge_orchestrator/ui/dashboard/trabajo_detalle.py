"""Panel derecho de «Trabajo»: diagnóstico y cronología del trabajo elegido.

El detalle habla en lenguaje de usuario y esconde lo técnico detrás de un
interruptor: un traceback en primer plano no ayuda a decidir qué hacer con
un documento atascado.
"""
from __future__ import annotations

from knowledge_orchestrator.ui.dashboard.inicio import InicioMixin
from knowledge_orchestrator.ui.snapshots import WorkItem


class DetalleMixin(InicioMixin):
    """Pintado del detalle, con y sin selección."""

    def _render_work_detail(self, item: WorkItem) -> None:
        self.detail_title_var.set(item.title)
        self.detail_badge_var.set(item.status_label)
        self.detail_path_var.set(item.path or item.filename)
        self.detail_id_var.set(
            f"ID de incidencia: {item.incident_id}"
            if item.incident_id is not None
            else f"ID de captura: {item.capture_id}"
        )
        badge_colors = {
            "attention": ("#311b20", self.colors["error"]),
            "completed": ("#173123", self.colors["success"]),
            "active": (self.colors["accent_dark"], self.colors["accent"]),
        }
        background, foreground = badge_colors[item.category]
        self.detail_badge.configure(bg=background, fg=foreground)

        if item.category == "attention":
            self.issue_title_var.set("No se pudo completar el trabajo.")
            recovery = item.error_message or (
                "Revisa el detalle técnico y vuelve a intentarlo cuando la causa esté resuelta."
            )
            self.issue_message_var.set(
                f"{recovery}\n\nTu archivo original se conserva; "
                "esta acción no modifica su contenido."
            )
        elif item.category == "completed":
            self.issue_title_var.set("Trabajo completado.")
            self.issue_message_var.set("El documento terminó el flujo y su historial permanece disponible.")
        else:
            self.issue_title_var.set("El documento sigue avanzando.")
            self.issue_message_var.set(
                item.progress_text
                or f"Fase actual: {item.phase}. La vista se actualiza automáticamente."
            )

        events = self.snapshots.work_events(item.capture_id)
        self.timeline.configure(state="normal")
        self.timeline.delete("1.0", "end")
        if not events:
            self.timeline.insert("end", "Todavía no hay eventos registrados para este trabajo.")
        else:
            for event in events:
                self.timeline.insert("end", f"{event.created_label}   ", "time")
                self.timeline.insert("end", f"{self._event_label(event.event_type)}\n", "event")
                self.timeline.insert("end", f"             {event.message}\n\n")
        self.timeline.configure(state="disabled")

        self.technical_var.set(
            f"Detalles técnicos: estado={item.status} · fase={item.phase} · modelo={item.model} "
            f"· intentos={item.attempt} · código={item.error_code or '—'}"
        )
        self.open_location_button.state(["!disabled"] if item.path else ["disabled"])
        can_retry = item.category == "attention" and (
            (bool(item.task_id) and item.status == "ERROR") or item.incident_id is not None
        )
        self.retry_button.state(["!disabled"] if can_retry else ["disabled"])
        if item.category == "active" and item.task_id and item.status in {"QUEUED", "PROCESSING"}:
            self.ignore_button.configure(text="Cancelar tarea")
            self.ignore_button.state(["!disabled"])
        elif item.category == "attention" and item.status in {"ERROR", "INGESTION_ERROR"}:
            self.ignore_button.configure(text="Ignorar este archivo")
            self.ignore_button.state(["!disabled"])
        else:
            self.ignore_button.configure(text="Ignorar este archivo")
            self.ignore_button.state(["disabled"])

    def _render_empty_detail(self) -> None:
        self.detail_title_var.set("Selecciona un trabajo")
        self.detail_badge_var.set("")
        self.detail_path_var.set("El detalle aparecerá aquí.")
        self.detail_id_var.set("")
        self.issue_title_var.set("No hay trabajos en esta vista.")
        self.issue_message_var.set("Cambia el filtro, limpia la búsqueda o importa un documento para empezar.")
        self.timeline.configure(state="normal")
        self.timeline.delete("1.0", "end")
        self.timeline.configure(state="disabled")
        self.technical_var.set("Detalles técnicos: —")
        for accion in (self.retry_button, self.open_location_button, self.ignore_button):
            accion.state(["disabled"])
