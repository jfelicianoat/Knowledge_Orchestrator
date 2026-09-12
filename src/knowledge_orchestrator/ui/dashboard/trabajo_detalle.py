"""Panel derecho de «Documentos»: diagnóstico y cronología del trabajo elegido.

El detalle habla en lenguaje de usuario y esconde lo técnico detrás de un
interruptor: un traceback en primer plano no ayuda a decidir qué hacer con
un documento atascado. Los pasos del recorrido dicen dónde está sin tener que
leer la cronología.
"""
from __future__ import annotations

import re

from knowledge_orchestrator.ui.dashboard.base import provider_error_text
from knowledge_orchestrator.ui.dashboard.estilo import FONT, FONT_SEMIBOLD, ICONS, STATUS_GLYPHS, TONES
from knowledge_orchestrator.ui.dashboard.inicio import InicioMixin
from knowledge_orchestrator.ui.snapshots import WorkEvent, WorkItem

STEPS = ("Recibido", "Validado", "Enviado", "Procesado", "Publicado")

#: Fase interna -> frase para el usuario. Antes se mostraba «Fase actual: ready».
PHASE_TEXT = {
    "staged": "Preparando el documento",
    "pending": "Esperando su planificación",
    "ready": "Listo para enviarse al Broker",
    "submitting": "Enviándose al Broker",
    "queued": "En la cola del Broker",
    "processing": "El Broker lo está procesando",
    "cancel_requested": "Cancelando el procesamiento",
    "success": "Resultado recibido; preparando la publicación",
}
#: Errores que ocurren antes de que el Broker acepte la tarea.
SUBMISSION_ERRORS = ("BROKER_OFFLINE", "BROKER_UNAVAILABLE", "SUBMISSION", "HTTP_", "AUTH")
ISSUE_ICONS = {"error": "error", "warning": "warning", "success": "check", "accent": "sync", "neutral": "info"}
_UNITS = re.compile(r"^(\d+)/(\d+) unidades$")


def work_progress(item: WorkItem) -> tuple[int, str]:
    """Paso actual del recorrido y su modo: active, waiting, failed, cancelled o done.

    Los pasos anteriores al índice están completados; `done` marca todos.
    """

    if item.incident_id is not None:
        return 1, "failed"
    if item.category == "completed":
        if item.status in {"CANCELLED", "REJECTED"}:
            return 3, "cancelled"
        return len(STEPS), "done"
    if item.category == "attention":
        if not item.task_id:
            return 1, "failed"
        code = (item.error_code or "").upper()
        return (2 if code.startswith(SUBMISSION_ERRORS) else 3), "failed"
    return {
        "STAGED": (0, "active"), "PENDING": (1, "waiting"), "READY": (2, "waiting"),
        "SUBMITTING": (2, "active"), "QUEUED": (3, "waiting"), "PROCESSING": (3, "active"),
        "CANCEL_REQUESTED": (3, "active"), "SUCCESS": (4, "active"),
    }.get(item.status, (1, "active"))


def humane_phase(item: WorkItem) -> str:
    units = _UNITS.match(item.progress_text or "")
    if units:
        return f"Progreso: {units.group(1)} de {units.group(2)} partes procesadas"
    if item.progress_text:
        return item.progress_text
    return PHASE_TEXT.get(item.phase.lower(), item.phase)


class DetalleMixin(InicioMixin):
    """Pintado del detalle, con y sin selección."""

    @staticmethod
    def _can_send_item(item: WorkItem) -> bool:
        return (
            bool(item.task_id) and item.status in {"READY", "ERROR"}
        ) or (
            item.category == "attention" and item.incident_id is not None
        )

    # ------------------------------------------------------------- pintado

    def _paint_badge(self, text: str, tone: str) -> None:
        background, foreground = TONES[tone]
        self.detail_badge_var.set(f"{STATUS_GLYPHS[tone]}  {text}" if text else "")
        self.detail_badge.configure(bg=background if text else self.colors["surface"], fg=foreground)

    def _paint_issue(self, tone: str) -> None:
        color = TONES[tone][1]
        self.issue_bar.configure(bg=color if tone != "neutral" else self.colors["border"])
        self.issue_icon.configure(text=ICONS[ISSUE_ICONS[tone]], fg=color)
        self.issue_title_label.configure(fg=color if tone in {"error", "warning"} else self.colors["text"])

    def _set_work_steps(self, state: tuple[int, str] | None) -> None:
        self._work_steps_state = state
        self._draw_work_steps()

    def _draw_work_steps(self) -> None:
        """Dibuja los cinco pasos del último estado; también al redimensionar."""

        canvas = self.work_steps
        canvas.delete("all")
        current = self._work_steps_state
        if current is None:
            return
        index, mode = current
        c = self.colors
        width = max(canvas.winfo_width(), 360)
        margin, radius, y = 44, 11, 20
        step = (width - 2 * margin) / (len(STEPS) - 1)
        xs = [margin + i * step for i in range(len(STEPS))]
        for i in range(len(STEPS) - 1):
            # El tramo se colorea si el paso siguiente ya se alcanzó sin fallo.
            reached = mode == "done" or i + 1 < index or (i + 1 == index and mode in {"active", "waiting"})
            canvas.create_line(xs[i] + radius + 3, y, xs[i + 1] - radius - 3, y, width=2,
                               fill=c["success"] if reached else c["border"])
        tone_for_mode = {"active": "accent", "waiting": "accent", "failed": "error", "cancelled": "neutral"}
        for i, (x, label) in enumerate(zip(xs, STEPS, strict=True)):
            if i < index or mode == "done":
                canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=c["success"], outline="")
                canvas.create_text(x, y, text="✓", fill="#0b1115", font=(FONT_SEMIBOLD, 10))
                label_color, weight = c["muted"], FONT
            elif i == index:
                tone = tone_for_mode.get(mode, "accent")
                color = TONES[tone][1]
                if mode == "failed":
                    canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=color, outline="")
                    canvas.create_text(x, y, text="✕", fill="#0b1115", font=(FONT_SEMIBOLD, 10))
                elif mode == "cancelled":
                    canvas.create_oval(x - radius, y - radius, x + radius, y + radius, outline=color, width=2)
                    canvas.create_text(x, y, text="–", fill=color, font=(FONT_SEMIBOLD, 10))
                else:
                    canvas.create_oval(x - radius, y - radius, x + radius, y + radius, outline=color, width=2)
                    if mode == "active":
                        canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=color, outline="")
                label_color, weight = color, FONT_SEMIBOLD
            else:
                canvas.create_oval(x - radius, y - radius, x + radius, y + radius, outline=c["border"], width=2)
                label_color, weight = c["faint"], FONT
            canvas.create_text(x, y + radius + 13, text=label, fill=label_color, font=(weight, 9))

    def _render_work_selection(self, items: list[WorkItem]) -> None:
        """Muestra detalle individual o un resumen seguro para acciones por lote."""

        if len(items) == 1:
            self._render_work_detail(items[0])
            return
        if not items:
            self._render_empty_detail()
            return

        retryable = [item for item in items if self._can_send_item(item)]
        self.detail_title_var.set(f"{len(items)} documentos seleccionados")
        self._paint_badge("Selección múltiple", "accent")
        self.detail_path_var.set("Se aplicará la acción a todos los documentos seleccionados que puedan reenviarse.")
        self.detail_id_var.set("")
        self._set_work_steps(None)
        self.issue_title_var.set(f"{len(retryable)} listos para enviar de nuevo")
        self.issue_message_var.set(
            "Los documentos se procesarán de forma independiente. Los que hayan cambiado de estado se omitirán."
        )
        self._paint_issue("accent")
        self.timeline.configure(state="normal")
        self.timeline.delete("1.0", "end")
        for item in items[:12]:
            tone = self._work_tone(item)
            self.timeline.insert("end", "●  ", f"dot_{tone}")
            self.timeline.insert("end", f"{item.title}   ", "event")
            self.timeline.insert("end", f"{item.status_label}\n")
        if len(items) > 12:
            self.timeline.insert("end", f"… y {len(items) - 12} más\n")
        self.timeline.configure(state="disabled")
        self.technical_var.set(f"Detalles técnicos: selección={len(items)} · reenviables={len(retryable)}")
        selected_label = "seleccionado" if len(retryable) == 1 else "seleccionados"
        self.retry_button.configure(text=f"Enviar {len(retryable)} {selected_label}")
        self.retry_button.state(["!disabled"] if retryable else ["disabled"])
        self.open_location_button.state(["disabled"])
        self.ignore_button.configure(text="Ignorar este archivo")
        self.ignore_button.state(["disabled"])

    def _render_work_detail(self, item: WorkItem) -> None:
        tone = self._work_tone(item)
        self.detail_title_var.set(item.title)
        self._paint_badge(item.status_label, tone)
        self.detail_path_var.set(self._middle_ellipsis(item.path or item.filename, 110))
        self.detail_id_var.set(
            f"ID de incidencia: {item.incident_id}"
            if item.incident_id is not None
            else f"ID de captura: {item.capture_id}"
        )
        self._set_work_steps(work_progress(item))

        if item.category == "attention":
            self.issue_title_var.set(
                "No se pudo leer el archivo." if item.incident_id is not None
                else "No se pudo completar el procesamiento."
            )
            recovery = provider_error_text(item.error_code, item.error_message) or (
                "Revisa el detalle técnico y vuelve a intentarlo cuando la causa esté resuelta."
            )
            self.issue_message_var.set(
                f"{recovery}\n\nTu archivo original se conserva; "
                "reintentarlo no modifica su contenido."
            )
        elif item.category == "completed":
            if item.status in {"CANCELLED", "REJECTED"}:
                self.issue_title_var.set("Documento cancelado.")
                self.issue_message_var.set("No se publicó. El archivo y su historial se conservan.")
            else:
                self.issue_title_var.set("Documento publicado en la biblioteca.")
                self.issue_message_var.set("Terminó el flujo; puedes consultarlo en Biblioteca. "
                                           "El historial permanece disponible.")
        else:
            self.issue_title_var.set("El documento sigue avanzando.")
            self.issue_message_var.set(f"{humane_phase(item)}. La vista se actualiza automáticamente.")
        self._paint_issue(tone)

        events = self.snapshots.work_events(item.capture_id)
        self.timeline.configure(state="normal")
        self.timeline.delete("1.0", "end")
        if not events:
            self.timeline.insert("end", "Todavía no hay eventos registrados para este documento.")
        else:
            for event in events:
                event_tone = self._event_tone(event.event_type)
                self.timeline.insert("end", "●  ", f"dot_{event_tone}")
                self.timeline.insert("end", f"{event.created_label}   ", "time")
                self.timeline.insert("end", f"{self._event_label(event.event_type)}\n", "event")
                detail = self._event_detail(event)
                if detail:
                    self.timeline.insert("end", f"{detail}\n", "message")
        self.timeline.configure(state="disabled")

        self.technical_var.set(
            f"Detalles técnicos: estado={item.status} · fase={item.phase} · modelo={item.model} "
            f"· intentos={item.attempt} · código={item.error_code or '—'}\nRuta: {item.path or item.filename}"
        )
        self.open_location_button.state(["!disabled"] if item.path else ["disabled"])
        can_retry = self._can_send_item(item)
        self.retry_button.configure(text="Enviar ahora" if item.status == "READY" else "Reintentar")
        self.retry_button.state(["!disabled"] if can_retry else ["disabled"])
        if item.category == "active" and item.task_id and item.status in {"QUEUED", "PROCESSING"}:
            self.ignore_button.configure(text="Cancelar procesamiento")
            self.ignore_button.state(["!disabled"])
        elif item.category == "attention" and item.status in {"ERROR", "INGESTION_ERROR"}:
            self.ignore_button.configure(text="Ignorar este archivo")
            self.ignore_button.state(["!disabled"])
        else:
            self.ignore_button.configure(text="Ignorar este archivo")
            self.ignore_button.state(["disabled"])

    @staticmethod
    def _event_detail(event: WorkEvent) -> str:
        """Mensaje del evento solo cuando dice algo que la etiqueta no dice."""

        message = event.message.strip()
        kind = event.event_type.upper()
        if not message or "->" in message or message.lower().startswith(("captura confirmada", "transición")):
            return ""
        if any(word in kind for word in ("ERROR", "FAILED", "WARNING", "CONFLICT", "REJECT")):
            return message
        return "" if kind.startswith("CAPTURE_") else message

    def _render_empty_detail(self) -> None:
        self.detail_title_var.set("Selecciona un documento")
        self._paint_badge("", "neutral")
        self.detail_path_var.set("El detalle aparecerá aquí.")
        self.detail_id_var.set("")
        self._set_work_steps(None)
        self.issue_title_var.set("No hay documentos en esta vista.")
        self.issue_message_var.set("Cambia el filtro, limpia la búsqueda o importa un documento para empezar.")
        self._paint_issue("neutral")
        self.timeline.configure(state="normal")
        self.timeline.delete("1.0", "end")
        self.timeline.configure(state="disabled")
        self.technical_var.set("Detalles técnicos: —")
        self.retry_button.configure(text="Reintentar")
        for accion in (self.retry_button, self.open_location_button, self.ignore_button):
            accion.state(["disabled"])


__all__ = ["DetalleMixin", "FONT", "PHASE_TEXT", "STEPS", "humane_phase", "work_progress"]
