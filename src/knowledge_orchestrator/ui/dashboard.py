from __future__ import annotations

import tkinter as tk
from collections.abc import Sequence
from dataclasses import replace
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
        self._profile_items = {}
        self._selected_profile_id: int | None = None
        self._selected_queue_task_id: str | None = None
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
        columns = ("pos", "estado", "fase", "modelo", "paso", "tiempo", "intentos", "titulo", "detalle")
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
            "detalle": "Detalle",
        }
        widths = {
            "pos": 42, "estado": 110, "fase": 140, "modelo": 160,
            "paso": 120, "tiempo": 90, "intentos": 70, "detalle": 340,
        }
        for column in columns:
            self.queue_tree.heading(column, text=headers[column])
            self.queue_tree.column(column, width=widths.get(column, 360), anchor="w")
        self.queue_tree.grid(row=0, column=0, sticky="nsew")
        self.queue_tree.bind("<<TreeviewSelect>>", lambda _event: self._select_queue_task())
        scrollbar = ttk.Scrollbar(self.queue_tab, orient="vertical", command=self.queue_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(self.queue_tab, orient="horizontal", command=self.queue_tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.queue_tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        queue_actions = ttk.Frame(self.queue_tab)
        queue_actions.grid(row=2, column=0, sticky="e", pady=(8, 0))
        self.cancel_task_button = ttk.Button(
            queue_actions,
            text="Cancelar tarea",
            command=self._cancel_selected_task,
        )
        self.cancel_task_button.pack(side="right")
        self.cancel_task_button.state(["disabled"])
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
        headings = {"pos": "#", "nombre": "Tema", "carpeta": "Carpeta", "perfil": "Perfil", "activo": "Activo"}
        for column, text in headings.items():
            self.topics_tree.heading(column, text=text)
            self.topics_tree.column(column, width=90 if column in {"pos", "activo"} else 260)
        self.topics_tree.grid(row=0, column=0, sticky="nsew")
        self.topics_tab.columnconfigure(0, weight=1)
        self.topics_tab.rowconfigure(0, weight=1)

    def _build_config(self) -> None:
        self.paths_var = tk.StringVar(value=data_root_label(self.runtime))
        ttk.Label(self.config_tab, text="Raíz de datos").grid(row=0, column=0, sticky="w")
        ttk.Label(self.config_tab, textvariable=self.paths_var).grid(row=0, column=1, sticky="w", padx=8)

        broker_frame = ttk.LabelFrame(self.config_tab, text="Broker AI · contrato y capacidades", padding=10)
        broker_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 8))
        broker_frame.columnconfigure(0, weight=1)
        self.capabilities_var = tk.StringVar(value="Esperando negociación con el Broker…")
        ttk.Label(
            broker_frame,
            textvariable=self.capabilities_var,
            wraplength=1080,
            justify="left",
        ).grid(row=0, column=0, sticky="ew")

        content = ttk.Panedwindow(self.config_tab, orient="horizontal")
        content.grid(row=2, column=0, columnspan=2, sticky="nsew")
        list_frame = ttk.Frame(content, padding=(0, 0, 10, 0))
        editor = ttk.LabelFrame(content, text="Política para nuevas tareas", padding=12)
        content.add(list_frame, weight=3)
        content.add(editor, weight=2)

        columns = ("nombre", "modelo", "estrategia", "datos", "activo")
        self.profiles_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        for column, text in {
            "nombre": "Perfil",
            "modelo": "Modelo",
            "estrategia": "Estrategia",
            "datos": "Datos",
            "activo": "Activo",
        }.items():
            self.profiles_tree.heading(column, text=text)
            self.profiles_tree.column(column, width=145 if column != "nombre" else 190)
        self.profiles_tree.grid(row=0, column=0, sticky="nsew")
        self.profiles_tree.bind("<<TreeviewSelect>>", lambda _event: self._select_profile())
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.profile_form = {
            "model": tk.StringVar(value="Automático (Broker)"),
            "strategy": tk.StringVar(value="single"),
            "classification": tk.StringVar(value="local_only"),
            "long_context": tk.StringVar(value="fail"),
            "compression": tk.StringVar(value="default del Broker"),
            "max_cost": tk.StringVar(value="0.05"),
            "human_review": tk.BooleanVar(value=False),
        }
        fields = [
            ("Modelo", "model", ("Automático (Broker)",)),
            ("Estrategia", "strategy", ("single", "mixture_of_agents", "auto")),
            ("Clasificación", "classification", ("public", "internal", "confidential", "local_only")),
            ("Contexto largo", "long_context", ("fail", "map_reduce")),
            (
                "Compresión",
                "compression",
                ("default del Broker", "off", "light", "medium", "aggressive"),
            ),
        ]
        self.profile_combos = {}
        for row, (label, key, values) in enumerate(fields):
            ttk.Label(editor, text=label).grid(row=row, column=0, sticky="w", pady=4)
            combo = ttk.Combobox(
                editor,
                textvariable=self.profile_form[key],
                values=values,
                state="readonly",
                width=25,
            )
            combo.grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=4)
            self.profile_combos[key] = combo
        ttk.Label(editor, text="Presupuesto por tarea (USD)").grid(row=5, column=0, sticky="w", pady=4)
        ttk.Entry(editor, textvariable=self.profile_form["max_cost"], width=27).grid(
            row=5, column=1, sticky="ew", padx=(10, 0), pady=4
        )
        ttk.Checkbutton(
            editor,
            text="Exigir revisión humana antes de publicar",
            variable=self.profile_form["human_review"],
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 4))
        ttk.Label(
            editor,
            text=(
                "La clasificación decide si el contenido puede salir a la nube. "
                "map_reduce delega al Broker los documentos que no caben; la compresión "
                "reduce prompts, pero puede perder detalle."
            ),
            wraplength=390,
            foreground="#555",
            justify="left",
        ).grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 12))
        self.save_profile_button = ttk.Button(editor, text="Guardar política", command=self._save_profile)
        self.save_profile_button.grid(row=8, column=1, sticky="e")
        self.save_profile_button.state(["disabled"])
        editor.columnconfigure(1, weight=1)
        self.config_tab.columnconfigure(1, weight=1)
        self.config_tab.rowconfigure(2, weight=1)

    def _refresh(self) -> None:
        self._drain_events()
        self._refresh_dashboard()
        self._refresh_queue()
        self._refresh_reviews()
        self._refresh_topics()
        self._refresh_profiles()
        self._refresh_capabilities()
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
            spinning = item.position == 1 and item.status == "PROCESSING"
            position = "⠋⠙⠹⠸"[self._spinner_index] if spinning else str(item.position)
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
                    item.progress_text,
                ),
            ))
        self._replace_tree(self.queue_tree, rows)
        if self._selected_queue_task_id not in {row_id for row_id, _values in rows}:
            self._selected_queue_task_id = None
            self.cancel_task_button.state(["disabled"])
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
                (
                    str(item.topic_id),
                    (item.position, item.name, item.folder, item.default_profile, "sí" if item.enabled else "no"),
                )
                for item in self.snapshots.topics()
            ],
        )

    def _refresh_profiles(self) -> None:
        profiles = self.snapshots.profiles()
        self._profile_items = {item.profile_id: item for item in profiles}
        self._replace_tree(
            self.profiles_tree,
            [
                (
                    str(item.profile_id),
                    (
                        item.name,
                        item.preferred_model or "Automático",
                        item.execution_strategy,
                        item.data_classification,
                        "sí" if item.enabled else "no",
                    ),
                )
                for item in profiles
            ],
        )

    def _select_queue_task(self) -> None:
        selection = self.queue_tree.selection()
        self._selected_queue_task_id = str(selection[0]) if selection else None
        self.cancel_task_button.state(
            ["!disabled"] if self._selected_queue_task_id else ["disabled"]
        )

    def _cancel_selected_task(self) -> None:
        task_id = self._selected_queue_task_id
        if not task_id:
            return
        if not messagebox.askyesno(
            "Cancelar tarea",
            "La tarea dejará de ejecutarse y su workflow se marcará como cancelado. ¿Continuar?",
        ):
            return
        if not self.runtime.broker_worker.request_cancel(task_id):
            messagebox.showerror(
                "No se pudo cancelar",
                "La tarea ya terminó o cambió de estado. Actualiza la cola e inténtalo de nuevo.",
            )
            return
        self.status_var.set(f"Cancelación solicitada para {task_id}")
        self.cancel_task_button.state(["disabled"])

    def _refresh_capabilities(self) -> None:
        capabilities = self.runtime.broker_worker.capabilities_snapshot()
        if not capabilities:
            self.profile_combos["strategy"].configure(
                values=available_profile_strategies(capabilities)
            )
            self.profile_combos["long_context"].configure(values=("fail", "map_reduce"))
            self.capabilities_var.set(
                "No se pudieron leer las capacidades. Puedes seguir enviando; el Broker validará la petición."
            )
            return
        strategies = available_profile_strategies(capabilities)
        self.profile_combos["strategy"].configure(values=strategies)
        long_context_values = (
            ("fail", "map_reduce")
            if capabilities.get("long_context_map_reduce", False)
            else ("fail",)
        )
        self.profile_combos["long_context"].configure(values=long_context_values)
        lanes = ", ".join(capabilities.get("work_lanes") or ["inference"])
        skills = ", ".join(capabilities.get("agent_skills") or []) or "ninguna"
        self.capabilities_var.set(
            f"Contrato {capabilities.get('contract_version', '?')} · Carriles: {lanes} · "
            f"Estrategias: {', '.join(strategies)} · Skills del Broker: {skills}"
        )

    def _select_profile(self) -> None:
        selection = self.profiles_tree.selection()
        if not selection:
            return
        profile_id = int(selection[0])
        item = self._profile_items.get(profile_id)
        if item is None:
            return
        self._selected_profile_id = profile_id
        models = ["Automático (Broker)", *self.snapshots.model_names()]
        if item.preferred_model and item.preferred_model not in models:
            models.append(item.preferred_model)
        self.profile_combos["model"].configure(values=models)
        self.profile_form["model"].set(item.preferred_model or "Automático (Broker)")
        self.profile_form["strategy"].set(item.execution_strategy)
        self.profile_form["classification"].set(item.data_classification)
        self.profile_form["long_context"].set(item.long_context)
        self.profile_form["compression"].set(item.prompt_compression or "default del Broker")
        self.profile_form["max_cost"].set(str(item.max_cost_usd))
        self.profile_form["human_review"].set(item.human_review_required)
        self.save_profile_button.state(["!disabled"])

    def _save_profile(self) -> None:
        if self._selected_profile_id is None:
            return
        try:
            max_cost = float(self.profile_form["max_cost"].get())
            current = self.runtime.profiles.get_profile(self._selected_profile_id)
            capabilities = self.runtime.broker_worker.capabilities_snapshot()
            strategy = self.profile_form["strategy"].get()
            if capabilities and strategy not in available_profile_strategies(capabilities):
                raise ValueError(f"El Broker actual no ofrece la estrategia {strategy}")
            long_context = self.profile_form["long_context"].get()
            if long_context == "map_reduce" and capabilities and not capabilities.get("long_context_map_reduce"):
                raise ValueError("El Broker actual no ofrece map_reduce")
            updated = replace(
                current,
                preferred_model=(
                    "" if self.profile_form["model"].get() == "Automático (Broker)"
                    else self.profile_form["model"].get()
                ),
                execution_strategy=strategy,
                data_classification=self.profile_form["classification"].get(),
                long_context=long_context,
                prompt_compression=(
                    None if self.profile_form["compression"].get() == "default del Broker"
                    else self.profile_form["compression"].get()
                ),
                max_cost_usd=max_cost,
                human_review_required=bool(self.profile_form["human_review"].get()),
            )
            saved = self.runtime.profiles.save_profile(updated)
        except (TypeError, ValueError, RuntimeError) as error:
            messagebox.showerror("No se pudo guardar la política", str(error))
            return
        self.status_var.set(
            f"Perfil {saved.name} actualizado. La política se aplicará a las tareas nuevas."
        )
        self._refresh_profiles()

    @staticmethod
    def _replace_tree(tree: ttk.Treeview, rows: Sequence[tuple[str, tuple[object, ...]]]) -> None:
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
            self.runtime.semantic_maintenance.reject(self._selected_review.candidate_id)
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


def available_profile_strategies(capabilities: dict) -> tuple[str, ...]:
    offered = capabilities.get("strategies")
    if not isinstance(offered, list):
        # Un fallo de discovery no equivale a una capacidad ausente. Estas son
        # las estrategias que sabe producir Knowledge Orchestrator.
        return ("single", "mixture_of_agents", "auto")
    allowed = tuple(
        strategy for strategy in ("single", "mixture_of_agents", "auto")
        if strategy in offered
    )
    return allowed or ("single",)
