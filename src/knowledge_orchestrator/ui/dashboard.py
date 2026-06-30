from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from knowledge_orchestrator.runtime import OrchestratorRuntime
from knowledge_orchestrator.ui.snapshots import ReviewItem, UiSnapshotService


class OrchestratorDashboard(tk.Tk):
    refresh_ms = 2000

    def __init__(self, runtime: OrchestratorRuntime) -> None:
        super().__init__()
        self.runtime = runtime
        self.snapshots = UiSnapshotService(runtime.database)
        self.title("Knowledge Orchestrator")
        self.geometry("1180x720")
        self.minsize(980, 560)
        self._spinner_index = 0
        self._selected_review: ReviewItem | None = None
        self._review_items: dict[str, ReviewItem] = {}
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)

    def start(self) -> None:
        self.runtime.start()
        self._refresh()
        self.mainloop()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        tabs = ttk.Notebook(self)
        tabs.grid(row=0, column=0, sticky="nsew")

        self.dashboard_tab = ttk.Frame(tabs, padding=12)
        self.queue_tab = ttk.Frame(tabs, padding=12)
        self.review_tab = ttk.Frame(tabs, padding=12)
        self.topics_tab = ttk.Frame(tabs, padding=12)
        self.config_tab = ttk.Frame(tabs, padding=12)
        tabs.add(self.dashboard_tab, text="Dashboard")
        tabs.add(self.queue_tab, text="Cola")
        tabs.add(self.review_tab, text="Revisión")
        tabs.add(self.topics_tab, text="Temas")
        tabs.add(self.config_tab, text="Configuración")

        self._build_dashboard()
        self._build_queue()
        self._build_review()
        self._build_topics()
        self._build_config()

        self.status_var = tk.StringVar(value="Arrancando...")
        ttk.Label(self, textvariable=self.status_var, anchor="w").grid(row=1, column=0, sticky="ew", padx=8, pady=4)

    def _build_dashboard(self) -> None:
        self.dashboard_vars = {
            "active": tk.StringVar(value="0"),
            "review": tk.StringVar(value="0"),
            "failed": tk.StringVar(value="0"),
            "published": tk.StringVar(value="0"),
            "broker": tk.StringVar(value="sin datos"),
            "broker_message": tk.StringVar(value=""),
        }
        labels = [
            ("Capturas activas", "active"),
            ("Pendientes de revisión", "review"),
            ("Fallidas", "failed"),
            ("Notas publicadas", "published"),
            ("Broker", "broker"),
        ]
        for index, (label, key) in enumerate(labels):
            frame = ttk.LabelFrame(self.dashboard_tab, text=label, padding=10)
            frame.grid(row=index // 3, column=index % 3, sticky="nsew", padx=6, pady=6)
            ttk.Label(frame, textvariable=self.dashboard_vars[key], font=("Segoe UI", 18)).pack(anchor="w")
        self.dashboard_tab.columnconfigure((0, 1, 2), weight=1)
        ttk.Label(
            self.dashboard_tab,
            textvariable=self.dashboard_vars["broker_message"],
            wraplength=1000,
            foreground="#555",
        ).grid(row=2, column=0, columnspan=3, sticky="ew", padx=6, pady=12)

    def _build_queue(self) -> None:
        columns = ("pos", "estado", "fase", "modelo", "paso", "tiempo", "intentos", "titulo")
        self.queue_tree = ttk.Treeview(self.queue_tab, columns=columns, show="headings", height=20)
        headers = {
            "pos": "#",
            "estado": "Estado",
            "fase": "Fase",
            "modelo": "Modelo",
            "paso": "Paso",
            "tiempo": "Tiempo",
            "intentos": "Intentos",
            "titulo": "Título",
        }
        widths = {"pos": 42, "estado": 110, "fase": 140, "modelo": 160, "paso": 120, "tiempo": 90, "intentos": 70}
        for column in columns:
            self.queue_tree.heading(column, text=headers[column])
            self.queue_tree.column(column, width=widths.get(column, 360), anchor="w")
        self.queue_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self.queue_tab, orient="vertical", command=self.queue_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.queue_tree.configure(yscrollcommand=scrollbar.set)
        self.queue_tab.columnconfigure(0, weight=1)
        self.queue_tab.rowconfigure(0, weight=1)

    def _build_review(self) -> None:
        self.review_tab.columnconfigure(0, weight=1)
        self.review_tab.rowconfigure(1, weight=1)
        columns = ("id", "relacion", "confianza", "impacto", "nota", "estado")
        self.review_tree = ttk.Treeview(self.review_tab, columns=columns, show="headings", height=8)
        for column, text in {
            "id": "ID",
            "relacion": "Relación",
            "confianza": "Confianza",
            "impacto": "Impacto",
            "nota": "Nota",
            "estado": "Estado",
        }.items():
            self.review_tree.heading(column, text=text)
            self.review_tree.column(column, width=120)
        self.review_tree.grid(row=0, column=0, sticky="nsew")
        self.review_tree.bind("<<TreeviewSelect>>", lambda _event: self._select_review())

        self.review_detail = tk.Text(self.review_tab, height=14, wrap="word")
        self.review_detail.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        buttons = ttk.Frame(self.review_tab)
        buttons.grid(row=2, column=0, sticky="e", pady=8)
        ttk.Button(buttons, text="Aprobar cambio", command=self._approve_selected).pack(side="left", padx=4)
        ttk.Button(buttons, text="Rechazar", command=self._reject_selected).pack(side="left", padx=4)

    def _build_topics(self) -> None:
        columns = ("pos", "nombre", "carpeta", "perfil", "activo")
        self.topics_tree = ttk.Treeview(self.topics_tab, columns=columns, show="headings")
        for column, text in {"pos": "#", "nombre": "Tema", "carpeta": "Carpeta", "perfil": "Perfil", "activo": "Activo"}.items():
            self.topics_tree.heading(column, text=text)
            self.topics_tree.column(column, width=90 if column in {"pos", "activo"} else 260)
        self.topics_tree.grid(row=0, column=0, sticky="nsew")
        self.topics_tab.columnconfigure(0, weight=1)
        self.topics_tab.rowconfigure(0, weight=1)

    def _build_config(self) -> None:
        self.paths_var = tk.StringVar(value=data_root_label(self.runtime))
        ttk.Label(self.config_tab, text="Raíz de datos").grid(row=0, column=0, sticky="w")
        ttk.Label(self.config_tab, textvariable=self.paths_var).grid(row=0, column=1, sticky="w", padx=8)
        columns = ("nombre", "modelo", "estrategia", "revision", "activo")
        self.profiles_tree = ttk.Treeview(self.config_tab, columns=columns, show="headings", height=12)
        for column, text in {
            "nombre": "Perfil",
            "modelo": "Modelo",
            "estrategia": "Estrategia",
            "revision": "Revisión humana",
            "activo": "Activo",
        }.items():
            self.profiles_tree.heading(column, text=text)
            self.profiles_tree.column(column, width=190)
        self.profiles_tree.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=12)
        self.config_tab.columnconfigure(1, weight=1)
        self.config_tab.rowconfigure(1, weight=1)

    def _refresh(self) -> None:
        self._drain_events()
        self._refresh_dashboard()
        self._refresh_queue()
        self._refresh_reviews()
        self._refresh_topics()
        self._refresh_profiles()
        self.after(self.refresh_ms, self._refresh)

    def _drain_events(self) -> None:
        events = self.runtime.bridge.drain()
        if events:
            event = events[-1]
            self.status_var.set(f"[{event.event_type}] {event.message}")

    def _refresh_dashboard(self) -> None:
        snapshot = self.snapshots.dashboard()
        self.dashboard_vars["active"].set(str(snapshot.active_captures))
        self.dashboard_vars["review"].set(str(snapshot.pending_review))
        self.dashboard_vars["failed"].set(str(snapshot.failed_captures))
        self.dashboard_vars["published"].set(str(snapshot.published_notes))
        self.dashboard_vars["broker"].set(snapshot.broker_status)
        self.dashboard_vars["broker_message"].set(snapshot.broker_message)

    def _refresh_queue(self) -> None:
        rows = []
        for item in self.snapshots.queue():
            position = "⠋⠙⠹⠸"[self._spinner_index] if item.position == 1 and item.status == "PROCESSING" else str(item.position)
            rows.append((
                item.task_id,
                (
                    position,
                    item.status,
                    item.phase,
                    item.model,
                    f"{item.step_kind} {item.completed_steps}/{item.total_steps}",
                    self._format_elapsed(item.elapsed_seconds),
                    item.attempt,
                    item.title,
                ),
            ))
        self._replace_tree(self.queue_tree, rows)
        self._spinner_index = (self._spinner_index + 1) % 4

    def _refresh_reviews(self) -> None:
        items = self.snapshots.reviews()
        self._review_items = {str(item.candidate_id): item for item in items}
        self._replace_tree(
            self.review_tree,
            [
                (
                    str(item.candidate_id),
                    (
                        item.candidate_id,
                        item.relation,
                        "" if item.confidence is None else f"{item.confidence:.2f}",
                        item.impact,
                        item.target_note_id,
                        item.status,
                    ),
                )
                for item in items
            ],
        )

    def _refresh_topics(self) -> None:
        self._replace_tree(
            self.topics_tree,
            [
                (str(item.topic_id), (item.position, item.name, item.folder, item.default_profile, "sí" if item.enabled else "no"))
                for item in self.snapshots.topics()
            ],
        )

    def _refresh_profiles(self) -> None:
        self._replace_tree(
            self.profiles_tree,
            [
                (
                    str(item.profile_id),
                    (
                        item.name,
                        item.preferred_model,
                        item.execution_strategy,
                        "sí" if item.human_review_required else "no",
                        "sí" if item.enabled else "no",
                    ),
                )
                for item in self.snapshots.profiles()
            ],
        )

    @staticmethod
    def _replace_tree(tree: ttk.Treeview, rows: list[tuple[str, tuple[object, ...]]]) -> None:
        selected = set(tree.selection())
        current = set(tree.get_children())
        incoming = {row_id for row_id, _ in rows}
        for row_id in current - incoming:
            tree.delete(row_id)
        for row_id, values in rows:
            if row_id in current:
                tree.item(row_id, values=values)
            else:
                tree.insert("", "end", iid=row_id, values=values)
        keep = tuple(row_id for row_id in selected if row_id in incoming)
        if keep:
            tree.selection_set(keep)

    def _select_review(self) -> None:
        selection = self.review_tree.selection()
        if not selection:
            return
        item = self._review_items.get(str(selection[0]))
        if item is None:
            return
        self._selected_review = item
        self.review_detail.configure(state="normal")
        self.review_detail.delete("1.0", "end")
        self.review_detail.insert(
            "1.0",
            f"Rationale:\n{item.rationale}\n\nDiff:\n{item.diff_text}\n\nBloqueo: {item.blocked_reason or '-'}",
        )
        self.review_detail.configure(state="disabled")

    def _approve_selected(self) -> None:
        if not self._selected_review:
            return
        try:
            self.runtime.semantic_maintenance.approve(self._selected_review.candidate_id)
        except Exception as error:
            messagebox.showerror("No se pudo aprobar", str(error))
        else:
            self.status_var.set(f"Candidato {self._selected_review.candidate_id} aprobado")
            self._selected_review = None
            self._refresh_reviews()

    def _reject_selected(self) -> None:
        if not self._selected_review:
            return
        try:
            self.runtime.semantic_repository.mark_candidate(
                self._selected_review.candidate_id,
                "REJECTED",
                reason="REJECTED_FROM_UI",
            )
        except Exception as error:
            messagebox.showerror("No se pudo rechazar", str(error))
        else:
            self.status_var.set(f"Candidato {self._selected_review.candidate_id} rechazado")
            self._selected_review = None
            self._refresh_reviews()

    @staticmethod
    def _format_elapsed(seconds: int) -> str:
        minutes, rest = divmod(max(0, seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes:02d}m"
        if minutes:
            return f"{minutes}m {rest:02d}s"
        return f"{rest}s"

    def _close(self) -> None:
        try:
            self.runtime.stop()
        finally:
            self.destroy()


def run_dashboard(runtime: OrchestratorRuntime) -> None:
    OrchestratorDashboard(runtime).start()


def data_root_label(runtime: OrchestratorRuntime) -> str:
    """Devuelve una raíz humana estable aunque PipelinePaths no exponga `root`."""
    paths = runtime.paths
    if paths.state.name == "state":
        return str(paths.state.parent)
    return str(paths.state)
