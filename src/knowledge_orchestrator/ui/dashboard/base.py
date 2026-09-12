"""Estado del panel y piezas que comparten todas las vistas.

Aquí está lo que no pertenece a ninguna pantalla: el estado de selección, la
creación de páginas, el cambio de página, el volcado de árboles y el cierre
limpio.
"""
from __future__ import annotations

import gc
import tkinter as tk
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import PureWindowsPath
from tkinter import ttk
from typing import Any

from knowledge_orchestrator.runtime import OrchestratorRuntime
from knowledge_orchestrator.services.broker_connection import BrokerConnectionStore
from knowledge_orchestrator.ui.dashboard.estilo import STATUS_GLYPHS, EstiloMixin
from knowledge_orchestrator.ui.snapshots import LibraryItem, ProfileItem, ReviewItem, UiSnapshotService, WorkItem
from knowledge_orchestrator.ui.startup import RuntimeStartup

#: Tipo de evento -> rótulo para la cronología y la actividad reciente. Sin
#: entrada, el rótulo se deriva del código en inglés: cada evento que el usuario
#: pueda ver debería estar aquí.
EVENT_LABELS = {
    "CAPTURE_COMPLETED": "Documento publicado",
    "BROKER_TASK_FAILED": "El Broker no pudo procesarlo", "BROKER_TASK_CANCELLED": "Procesamiento cancelado",
    "BROKER_CANCEL_PENDING": "Cancelación pendiente", "BROKER_UNAVAILABLE": "Broker no disponible",
    "BROKER_CYCLE_ERROR": "Incidencia del Broker", "BROKER_WORKER_CRASH": "Fallo del proceso del Broker",
    "BROKER_CONTRACT_WARNING": "Aviso de compatibilidad del Broker",
    "BROKER_CAPABILITIES_UNAVAILABLE": "Capacidades del Broker no disponibles",
    "PUBLICATION_PREPARED": "Publicación preparada", "PUBLICATION_FAILED": "Error al publicar",
    "PUBLICATION_CONFLICT": "Conflicto al publicar", "NOTE_REJECTED": "Nota rechazada",
    "INGESTION_REJECTED": "Archivo rechazado", "INGESTION_ERROR": "Error de ingesta",
    "INGESTION_CRASH": "Fallo de ingesta", "SOURCE_CHANGED_AFTER_STAGING": "El archivo cambió al prepararlo",
    "CAPTURE_CHANGED_AFTER_RECEIPT": "El documento cambió tras recibirlo",
    "MAINTENANCE_CANDIDATE_STATE_CHANGED": "Propuesta actualizada",
    "MAINTENANCE_PROPOSAL_REVISED": "Propuesta revisada", "MAINTENANCE_PROPOSAL_REJECTED": "Propuesta descartada",
    "SEMANTIC_UPDATE_APPLIED": "Cambio aplicado a la nota",
    "MAINTENANCE_REVERSION_CONFIRMED": "Reversión confirmada", "MAINTENANCE_REVERSION_APPLIED": "Reversión aplicada",
    "MAINTENANCE_REVERSION_CONFLICT": "Conflicto en la reversión",
    "CLAIM_STATE_CHANGED": "Vigencia actualizada", "CLAIM_STATE_REVIEWED": "Vigencia revisada",
    "CLAIM_MANUAL_LOCK_CHANGED": "Bloqueo manual cambiado",
    "SEMANTIC_CONTRACT_FAILED": "Respuesta de análisis no válida",
    "SOURCE_CREATED": "Fuente añadida", "SOURCE_CONFIGURED": "Fuente configurada",
    "SOURCE_CHECK_REQUESTED": "Comprobación solicitada", "SOURCE_CHECK_RECOVERED": "Comprobación recuperada",
    "SOURCE_CHANGE_ACCEPTED": "Novedad aceptada", "SOURCE_CHANGE_DELIVERED": "Novedad incorporada",
    "SOURCE_DELIVERY_ERROR": "Error al incorporar una novedad",
    "REVIEW_BATCH_PREVIEWED": "Lote preparado", "REVIEW_BATCH_CONFIRMED": "Lote confirmado",
    "REVIEW_BATCH_COMPLETED": "Lote completado", "REVIEW_BATCH_ITEM_FINISHED": "Elemento del lote aplicado",
    "REVIEW_BATCH_RECOVERY_REQUIRED": "Lote pendiente de recuperar",
    "AUTOMATION_POLICY_CREATED": "Política creada", "AUTOMATION_POLICY_REVISED": "Política revisada",
    "AUTOMATION_POLICY_ENABLED": "Política autorizada", "AUTOMATION_POLICY_DISABLED": "Política desactivada",
    "AUTOMATION_PAUSED": "Autoaprobación en pausa", "AUTOMATION_RESUMED": "Autoaprobación reanudada",
    "AUTOMATION_SIMULATED": "Simulación de política", "AUTOMATION_RUN_QUEUED": "Ejecución programada",
    "AUTOMATION_RUN_FINISHED": "Ejecución terminada", "AUTOMATION_ITEM_FINISHED": "Aplicado por una política",
    "AUTOMATION_RECOVERY_REQUIRED": "Ejecución pendiente de recuperar",
    "QUERY_CREATED": "Consulta creada", "API_INGESTION_RECEIVED": "Documento recibido por API",
    "API_INGESTION_DELIVERED": "Documento de API incorporado",
    "INGESTION_RESULT": "Importación", "NOTES_PUBLISHED": "Notas publicadas",
    "BROKER_QUEUE_UPDATED": "Cola actualizada", "BROKER_TASKS_UPDATED": "Tareas actualizadas",
    "SEMANTIC_JOBS_UPDATED": "Análisis actualizados", "BROKER_MODELS_UPDATED": "Modelos actualizados",
    "BROKER_CAPABILITIES_UPDATED": "Capacidades del Broker", "BROKER_CONNECTION_UPDATED": "Conexión actualizada",
}

#: Eventos del worker que dicen si el Broker responde. Solo viajan por el puente
#: de eventos (no se guardan en SQLite), así que la vista los recoge al vuelo:
#: antes el resumen leía la base y el Broker figuraba siempre «sin comprobar».
BROKER_STATUS_EVENTS = {"BROKER_ONLINE": "online", "BROKER_OFFLINE": "incidencia",
                        "BROKER_CYCLE_ERROR": "incidencia", "BROKER_WORKER_CRASH": "incidencia"}

INGESTION_MESSAGES = {
    "DUPLICATE_CAPTURE": ("Este documento ya estaba importado; no se ha duplicado. "
                          "La copia repetida queda en cuarentena."),
    "UNSUPPORTED_FILE": "Solo se admiten documentos Markdown (.md).",
    "FILE_LOCKED": "El archivo está en uso por otro programa; aparecerá en «Necesitan atención» para reintentarlo.",
    "FILE_UNSTABLE": "El archivo aún se está escribiendo; aparecerá en «Necesitan atención» para reintentarlo.",
    "TRANSCRIPTION_MISSING": "El documento no incluye transcripción; queda en cuarentena sin procesar.",
    "INGESTION_CANCELLED": "Importación interrumpida al cerrar el servicio; se reanudará al volver a abrir.",
}


def provider_error_text(code: str | None, message: str) -> str:
    """Traduce el fallo del proveedor a algo que diga qué hacer.

    El Broker explica el suyo en su idioma («done_reason=length»); aquí hace
    falta la causa y la salida, que está en Ajustes.
    """

    lowered = message.lower()
    if code == "INVALID_PROVIDER_RESPONSE" and ("done_reason=length" in lowered or "max_output_tokens" in lowered):
        return ("El modelo agotó su presupuesto de respuesta razonando antes de contestar. "
                "Se reintenta una vez con el doble de presupuesto; si vuelve a fallar, elige en Ajustes "
                "un modelo sin razonamiento o sube «Longitud máxima de la respuesta».")
    return message


def ingestion_status_text(details: Mapping[str, Any], message: str) -> str:
    """Resultado de una importación en una frase: antes llegaba «$: falta la apertura…»."""

    if details.get("accepted"):
        return "Documento importado: se procesará automáticamente."
    code = str(details.get("error_code") or "")
    if code in INGESTION_MESSAGES:
        return INGESTION_MESSAGES[code]
    reason = message[3:] if message.startswith("$: ") else message
    return (f"No se pudo importar: el archivo no sigue el formato de captura ({reason}). "
            "Queda en cuarentena; el original no se modifica.")


class DashboardBase(EstiloMixin):
    """Ventana con estado, páginas y utilidades, todavía sin vistas."""

    refresh_ms = 2000

    # -- Puestos por los `_build_*` de cada vista. Son el contrato entre la
    # -- construcción y el resto del panel: si una vista deja de crear su
    # -- widget, el fallo sale aquí y no cuando alguien pulsa un botón.
    page_host: tk.Frame
    pages: dict[str, tk.Widget]
    _scrollable_canvases: dict[str, tk.Canvas]
    nav_buttons: dict[str, tk.Frame]
    status_var: tk.StringVar
    refresh_button: tk.Button
    service_var: tk.StringVar
    broker_var: tk.StringVar
    clock_var: tk.StringVar
    dashboard_vars: dict[str, tk.StringVar]
    dashboard_card_vars: dict[str, tk.StringVar]
    system_message_var: tk.StringVar
    home_attention: ttk.Treeview
    search_var: tk.StringVar
    search_entry: ttk.Entry
    work_tree: ttk.Treeview
    work_summary_var: tk.StringVar
    detail_title_var: tk.StringVar
    detail_badge: tk.Label
    detail_badge_var: tk.StringVar
    detail_path_var: tk.StringVar
    detail_id_var: tk.StringVar
    issue_frame: tk.Frame
    issue_title_var: tk.StringVar
    issue_message_var: tk.StringVar
    timeline: tk.Text
    work_steps: tk.Canvas
    _work_steps_state: tuple[int, str] | None
    issue_bar: tk.Frame
    issue_icon: tk.Label
    issue_title_label: tk.Label
    service_dot: tk.Label
    broker_dot: tk.Label
    technical_var: tk.StringVar
    technical_button: tk.Button
    technical_label: tk.Label
    retry_button: ttk.Button
    open_location_button: ttk.Button
    ignore_button: ttk.Button
    review_tree: ttk.Treeview
    review_detail: tk.Text
    review_approve_button: ttk.Button
    review_reject_button: ttk.Button
    library_tree: ttk.Treeview
    library_search_var: tk.StringVar
    library_search_entry: ttk.Entry
    library_summary_var: tk.StringVar
    library_title_var: tk.StringVar
    library_meta_var: tk.StringVar
    library_path_var: tk.StringVar
    library_open_button: ttk.Button
    topics_tree: ttk.Treeview
    paths_var: tk.StringVar
    inbox_path_var: tk.StringVar
    results_path_var: tk.StringVar
    path_status_var: tk.StringVar
    broker_url_var: tk.StringVar
    broker_token_var: tk.StringVar
    broker_credential_var: tk.StringVar
    profiles_tree: ttk.Treeview
    capabilities_var: tk.StringVar
    save_profile_button: ttk.Button
    edit_prompt_button: ttk.Button

    # -- Costuras entre vistas. Las implementa quien las tiene: el refresco
    # -- completo lo conoce la ventana entera, y la lista de trabajos, su
    # -- vista. Declararlas aquí es lo que permite comprobarlas de verdad.

    def _refresh(self, *, force: bool = False) -> None:
        raise NotImplementedError  # pragma: no cover - lo implementa la ventana completa

    def _refresh_work_list(self, *, select_first: bool = False) -> None:
        raise NotImplementedError  # pragma: no cover - lo implementa la vista de trabajo

    def _refresh_library(self) -> None:
        raise NotImplementedError  # pragma: no cover - lo implementa la vista de biblioteca

    def __init__(self, runtime: OrchestratorRuntime) -> None:
        super().__init__()
        self.runtime = runtime
        self._startup = RuntimeStartup(runtime)
        self.snapshots = UiSnapshotService(runtime.database)
        self.connection_store = BrokerConnectionStore(runtime.paths)
        self.title("Knowledge Orchestrator")
        self.geometry("1440x900")
        self.minsize(1080, 680)
        self.configure(background=self.colors["root"])

        self._live_broker: tuple[str, str] | None = None
        self._selected_review: ReviewItem | None = None
        self._review_items: dict[str, ReviewItem] = {}
        self._library_items: dict[str, LibraryItem] = {}
        self._selected_library_id: int | None = None
        self._library_search_job: str | None = None
        self._profile_items: dict[int, ProfileItem] = {}
        self._selected_profile_id: int | None = None
        self._work_items: dict[str, WorkItem] = {}
        self._selected_work_id: str | None = None
        self._selected_work_ids: tuple[str, ...] = ()
        self._work_filter = "active"
        self._work_selection_initialized = False
        self._auto_refresh = True
        self._current_page = "work"
        self._refresh_job: str | None = None
        self._scrollable_canvases = {}
        self.bind_all("<MouseWheel>", self._scroll_active_page, add="+")

    def _new_page(self, name: str) -> tk.Frame:
        page = tk.Frame(self.page_host, bg=self.colors["surface"])
        page.grid(row=0, column=0, sticky="nsew")
        self.pages[name] = page
        return page

    def _new_scrollable_page(self, name: str) -> tk.Frame:
        """Crea una página cuyo contenido sigue accesible en ventanas bajas."""

        outer = tk.Frame(self.page_host, bg=self.colors["surface"], highlightthickness=0)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)
        # width/height mínimos: el lienzo no debe pedir tamaño a la ventana;
        # lo recibe de la rejilla. Sin esto Ajustes ensanchaba la ventana.
        canvas = tk.Canvas(
            outer,
            bg=self.colors["surface"],
            highlightthickness=0,
            borderwidth=0,
            width=1,
            height=1,
        )
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        content = tk.Frame(canvas, bg=self.colors["surface"], highlightthickness=0)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")

        def fit_content_width(event: tk.Event) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        def update_scroll_region(_event: tk.Event) -> None:
            bounds = canvas.bbox("all")
            if bounds is not None:
                canvas.configure(scrollregion=bounds)

        canvas.bind("<Configure>", fit_content_width)
        content.bind("<Configure>", update_scroll_region)
        self.pages[name] = outer
        self._scrollable_canvases[name] = canvas
        return content

    def _scroll_active_page(self, event: tk.Event) -> None:
        canvas = self._scrollable_canvases.get(self._current_page)
        if canvas is None or not canvas.winfo_ismapped() or not event.delta:
            return
        canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def _page_heading(self, page: tk.Frame, title: str, subtitle: str) -> None:
        heading = tk.Frame(page, bg=self.colors["surface"])
        heading.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 16))
        tk.Label(heading, text=title, bg=self.colors["surface"], fg=self.colors["text"],
                 font=("Segoe UI Semibold", 20), anchor="w").pack(fill="x")
        tk.Label(heading, text=subtitle, bg=self.colors["surface"], fg=self.colors["muted"],
                 font=("Segoe UI", 10), anchor="w", justify="left").pack(fill="x", pady=(2, 0))

    def _paint_navigation(self, page: str) -> None:
        """Marca la entrada activa de la navegación; la pinta quien la construye."""

    def _show_page_event(self, page: str, _event: object = None) -> None:
        """Adaptador para `bind`: los manejadores reciben el evento y aquí no hace falta."""

        self._show_page(page)

    @staticmethod
    def _invoke(action: Callable[[], object], _event: object = None) -> None:
        action()

    def _show_page(self, page: str) -> None:
        self._current_page = page
        self.pages[page].tkraise()
        self._paint_navigation(page)
        if page == "work":
            self.after_idle(self.search_entry.focus_set)
        elif page == "library":
            self._refresh_library()
            self.after_idle(self.library_search_entry.focus_set)

    def _drain_events(self) -> None:
        events = self.runtime.bridge.drain()
        for event in events:
            status = BROKER_STATUS_EVENTS.get(event.event_type)
            if status is not None:
                self._live_broker = (status, event.message)
        if events:
            event = events[-1]
            if event.event_type == "INGESTION_RESULT":
                self.status_var.set(ingestion_status_text(event.details or {}, event.message))
                return
            # El mensaje puede ser un error técnico del cliente HTTP en inglés
            # («All connection attempts failed»): delante va qué ha pasado.
            label = self._event_label(event.event_type)
            self.status_var.set(f"{label}: {event.message}" if event.message and label != event.message
                                else event.message or label)

    def _selected_item(self) -> WorkItem | None:
        return self._work_items.get(self._selected_work_id or "")

    def _selected_items(self) -> tuple[WorkItem, ...]:
        """Devuelve toda la selección visible en el mismo orden que la lista."""

        return tuple(
            self._work_items[item_id]
            for item_id in self._selected_work_ids
            if item_id in self._work_items
        )

    @staticmethod
    def _replace_tree(
        tree: ttk.Treeview,
        rows: Sequence[tuple[str, tuple[object, ...]]],
        *,
        texts: dict[str, str] | None = None,
        tags: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        selected = set(tree.selection())
        current = set(tree.get_children())
        incoming = {row_id for row_id, _ in rows}
        for row_id in current - incoming:
            tree.delete(row_id)
        for row_id, values in rows:
            options: dict[str, Any] = {"values": values}
            if texts is not None:
                options["text"] = texts.get(row_id, "")
            if tags is not None:
                options["tags"] = tags.get(row_id, ())
            if row_id in current:
                tree.item(row_id, **options)
            else:
                tree.insert("", "end", iid=row_id, **options)
        keep = tuple(row_id for row_id in selected if row_id in incoming)
        if keep:
            tree.selection_set(keep)

    @staticmethod
    def _work_row_text(item: WorkItem) -> str:
        # En la lista basta el nombre del archivo: la ruta completa se truncaba
        # y no aportaba nada. Sigue entera en el detalle.
        location = PureWindowsPath(item.path).name if item.path else item.filename
        location = location or item.filename
        if location == item.title:
            # Un archivo que no se pudo leer no tiene título propio: repetir el
            # nombre no aporta; decir dónde está, sí.
            location = "En la carpeta vigilada" if item.incident_id is not None else ""
        return f"{item.title}\n{location}"

    @staticmethod
    def _work_tone(item: WorkItem) -> str:
        """Tono visual del estado: el color nunca va solo, siempre con texto."""

        if item.incident_id is not None:
            return "warning"
        if item.category == "attention":
            return "error"
        if item.category == "completed":
            return "neutral" if item.status in {"CANCELLED", "REJECTED"} else "success"
        return "neutral" if item.status in {"READY", "PENDING", "STAGED"} else "accent"

    def _status_text(self, item: WorkItem) -> str:
        return f"{STATUS_GLYPHS[self._work_tone(item)]}  {item.status_label}"

    @staticmethod
    def _relative_label(value: str | None) -> str:
        """«hace 5 min» para la lista; la hora exacta queda en la cronología."""

        if not value:
            return "—"
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return str(value)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        seconds = int((datetime.now(timezone.utc) - moment).total_seconds())
        if seconds < 60:
            return "ahora mismo"
        if seconds < 3600:
            return f"hace {seconds // 60} min"
        if seconds < 86400:
            return f"hace {seconds // 3600} h"
        if seconds < 7 * 86400:
            return f"hace {seconds // 86400} d"
        return moment.astimezone().strftime("%d/%m/%Y")

    @staticmethod
    def _middle_ellipsis(text: str, limit: int = 90) -> str:
        if len(text) <= limit:
            return text
        keep = (limit - 1) // 2
        return f"{text[:keep]}…{text[-keep:]}"

    @staticmethod
    def _event_label(event_type: str) -> str:
        labels = {
            "CAPTURE_STAGED": "Documento preparado", "CAPTURE_PENDING": "Validación completada",
            "BROKER_TASK_ACCEPTED": "Broker aceptó la tarea", "CAPTURE_PROCESSING": "Procesamiento iniciado",
            "CAPTURE_COMPLETED": "Trabajo completado", "MANUAL_RETRY_REQUESTED": "Reintento solicitado",
            "CAPTURE_IGNORED": "Incidencia ignorada",
            "BROKER_RESULT_WARNING": "Aviso del Broker",
            "BROKER_CITATION_WARNING": "Revisión de citas necesaria",
            "BROKER_ONLINE": "Broker disponible", "BROKER_OFFLINE": "Broker no disponible",
            "KNOWLEDGE_RECONCILED": "Coherencia comprobada", "API_REQUEST": "Consulta por API",
            "FILE_LOCKED": "Archivo bloqueado", "FILE_UNSTABLE": "Archivo inestable",
            "INGESTION_CANCELLED": "Ingesta cancelada",
        }
        return EVENT_LABELS.get(event_type) or labels.get(event_type, event_type.replace("_", " ").capitalize())

    @staticmethod
    def _format_elapsed(seconds: int) -> str:
        minutes, rest = divmod(max(0, seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes:02d}m"
        if minutes:
            return f"{minutes}m"
        return f"{rest}s"

    def destroy(self) -> None:
        if self.__dict__.get('_released'):
            return  # segunda llamada (limpieza de pruebas, cierre repetido): ya no queda nada
        # Tk removes commands on destruction but leaves their timers registered.
        # Cancel only callbacks owned by this root; child panels cancel their own.
        commands = set(getattr(self, '_tclCommands', None) or ())
        for job in self.tk.call('after', 'info'):
            script = self.tk.call('after', 'info', job)[0]
            if script in commands:
                self.after_cancel(job)
        super().destroy()
        self._release_after_destroy()

    def _release_after_destroy(self) -> None:
        """Libera la ventana ya destruida en este hilo, el de Tk.

        Cada widget guardado como atributo apunta a su padre y, por él, a esta
        ventana: el conjunto es un ciclo que solo el recolector libera, en el
        hilo que esté activo en ese momento. Si es un hilo de lectura, Python
        borra ahí las variables Tk y el intérprete Tcl, y el proceso aborta con
        «Tcl_AsyncDelete: async handler deleted by the wrong thread»
        (reproducido: dos pruebas con la ventana seguidas de otra con hilos).
        Se vacían los atributos, salvo el intérprete y el nombre de la ventana,
        y se recoge la basura aquí mismo.
        """

        keep: dict[str, Any] = {name: self.__dict__[name] for name in ('tk', '_w') if name in self.__dict__}
        self.__dict__.clear()
        self.__dict__.update(keep, _released=True)
        gc.collect()

    def _close(self) -> None:
        if self._library_search_job is not None:
            self.after_cancel(self._library_search_job)
            self._library_search_job = None
        if self._refresh_job is not None:
            try:
                self.after_cancel(self._refresh_job)
            except tk.TclError:
                pass
            self._refresh_job = None
        try:
            self._startup.cancel()
        finally:
            self.destroy()
