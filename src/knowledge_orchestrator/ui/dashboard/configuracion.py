"""Vista «Configuración»: la política que se aplica a los trabajos nuevos.

Las estrategias que se ofrecen salen de lo que el Broker dice admitir, no de
una lista fija: ofrecer una estrategia que el Broker no tiene es prometer
algo que fallará al primer trabajo.
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from functools import partial
from tkinter import filedialog, messagebox, ttk

from knowledge_orchestrator.runtime import OrchestratorRuntime
from knowledge_orchestrator.services.broker_connection import (
    BrokerConnectionError,
    load_broker_settings,
)
from knowledge_orchestrator.services.path_settings import PipelinePathStore
from knowledge_orchestrator.ui.dashboard.temas import TemasMixin

STRATEGY_LABELS = {
    "single": "Respuesta directa",
    "mixture_of_agents": "Consenso entre modelos",
    "auto": "Automático según la tarea",
}
CLASSIFICATION_LABELS = {
    "local_only": "Solo procesamiento local",
    "confidential": "Confidencial",
    "internal": "Uso interno",
    "public": "Contenido público",
}
LONG_CONTEXT_LABELS = {
    "fail": "Dividir el documento localmente",
    "map_reduce": "Procesar documentos extensos por bloques",
}
COMPRESSION_LABELS = {
    "": "Decisión automática del Broker",
    "off": "Sin compresión",
    "light": "Ligera",
    "medium": "Media",
    "aggressive": "Alta",
}


def _label_for(mapping: dict[str, str], value: str | None) -> str:
    normalized = value or ""
    if normalized in mapping:
        return mapping[normalized]
    return normalized or next(iter(mapping.values()))


def _value_for(mapping: dict[str, str], label: str) -> str:
    return next((value for value, visible in mapping.items() if visible == label), label)


def data_root_label(runtime: OrchestratorRuntime) -> str:
    """Devuelve una raíz humana estable aunque PipelinePaths no exponga `root`."""
    paths = runtime.paths
    if paths.state.name == "state":
        return str(paths.state.parent)
    return str(paths.state)


def available_profile_strategies(capabilities: dict) -> tuple[str, ...]:
    offered = capabilities.get("strategies")
    if not isinstance(offered, list):
        return ("single", "mixture_of_agents", "auto")
    allowed = tuple(strategy for strategy in ("single", "mixture_of_agents", "auto") if strategy in offered)
    return allowed or ("single",)


def profile_save_enabled(selected_profile_id: int | None, *, dirty: bool) -> bool:
    return selected_profile_id is not None and dirty


class ConfiguracionMixin(TemasMixin):
    """Raíz de datos, capacidades del Broker y edición de perfiles."""

    def _build_config(self) -> None:
        page = self._new_scrollable_page("config")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(4, weight=1)
        self._page_heading(page, "Ajustes", "Define cómo se procesarán los documentos nuevos.")
        self._path_store = PipelinePathStore()
        self.paths_var = tk.StringVar(value=data_root_label(self.runtime))
        self.inbox_path_var = tk.StringVar(value=str(self.runtime.paths.inbox))
        self.results_path_var = tk.StringVar(value=str(self.runtime.paths.obsidian_vault))
        self.path_status_var = tk.StringVar(
            value="Entrada: aquí se recogen archivos · Resultados: aquí se publican los apuntes."
        )
        info = tk.Frame(page, bg=self.colors["raised"], highlightbackground=self.colors["border"], highlightthickness=1)
        info.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 14))
        tk.Label(
            info, text="Carpetas del proceso", bg=self.colors["raised"], fg=self.colors["text"],
            font=("Segoe UI Semibold", 10),
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(12, 8))
        locations = (
            ("Datos internos", self.paths_var),
            ("Entrada de archivos", self.inbox_path_var),
            ("Resultados / apuntes", self.results_path_var),
        )
        for row, (label, variable) in enumerate(locations, start=1):
            tk.Label(
                info, text=label, bg=self.colors["raised"], fg=self.colors["muted"], font=("Segoe UI", 9),
            ).grid(row=row, column=0, sticky="w", padx=(14, 8), pady=4)
            ttk.Entry(info, textvariable=variable, style="Dark.TEntry").grid(
                row=row, column=1, sticky="ew", pady=4
            )
            ttk.Button(
                info,
                text="Elegir…",
                style="Secondary.TButton",
                command=partial(self._choose_folder, variable),
            ).grid(row=row, column=2, padx=10, pady=4)
        ttk.Button(
            info, text="Guardar carpetas", style="Accent.TButton", command=self._save_paths
        ).grid(row=4, column=2, sticky="e", padx=10, pady=(6, 8))
        tk.Label(
            info, textvariable=self.path_status_var, bg=self.colors["raised"], fg=self.colors["muted"],
            font=("Segoe UI", 9), wraplength=1050, justify="left",
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=14, pady=(6, 8))
        self.capabilities_var = tk.StringVar(value="Esperando negociación con el Broker…")
        tk.Label(info, textvariable=self.capabilities_var, bg=self.colors["raised"], fg=self.colors["muted"],
                 font=("Segoe UI", 9), wraplength=1250, justify="left").grid(
            row=5, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 12)
        )
        info.columnconfigure(1, weight=1)

        connection = tk.Frame(
            page, bg=self.colors["raised"], highlightbackground=self.colors["border"], highlightthickness=1
        )
        connection.grid(row=3, column=0, sticky="ew", padx=24, pady=(0, 14))
        connection.columnconfigure(1, weight=1)
        tk.Label(
            connection, text="Conexión a AI Broker", bg=self.colors["raised"], fg=self.colors["text"],
            font=("Segoe UI Semibold", 10),
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=14, pady=(12, 8))
        self.broker_url_var = tk.StringVar(value=self.runtime.broker_worker.settings.base_url)
        self.broker_token_var = tk.StringVar(value="")
        self.broker_credential_var = tk.StringVar(value=self._broker_credential_status())
        tk.Label(
            connection, text="Dirección", bg=self.colors["raised"], fg=self.colors["muted"],
            font=("Segoe UI", 9),
        ).grid(row=1, column=0, sticky="w", padx=(14, 8), pady=5)
        ttk.Entry(connection, textvariable=self.broker_url_var, style="Dark.TEntry").grid(
            row=1, column=1, sticky="ew", pady=5
        )
        tk.Label(
            connection, text="Token", bg=self.colors["raised"], fg=self.colors["muted"],
            font=("Segoe UI", 9),
        ).grid(row=2, column=0, sticky="w", padx=(14, 8), pady=5)
        ttk.Entry(
            connection, textvariable=self.broker_token_var, show="●", style="Dark.TEntry"
        ).grid(row=2, column=1, sticky="ew", pady=5)
        ttk.Button(
            connection, text="Guardar conexión", style="Accent.TButton", command=self._save_broker_connection
        ).grid(row=1, column=2, rowspan=2, sticky="ns", padx=10, pady=5)
        ttk.Button(
            connection, text="Eliminar token", style="Secondary.TButton", command=self._clear_broker_token
        ).grid(row=1, column=3, rowspan=2, sticky="ns", padx=(0, 14), pady=5)
        tk.Label(
            connection, textvariable=self.broker_credential_var, bg=self.colors["raised"],
            fg=self.colors["muted"], font=("Segoe UI", 9), anchor="w",
        ).grid(row=3, column=0, columnspan=4, sticky="ew", padx=14, pady=(5, 12))

        content = tk.PanedWindow(page, orient="horizontal", bg=self.colors["border"], sashwidth=2, bd=0)
        content.grid(row=4, column=0, sticky="nsew", padx=24, pady=(0, 24))
        list_frame = tk.Frame(content, bg=self.colors["surface"])
        editor = tk.Frame(content, bg=self.colors["surface"])
        content.add(list_frame, minsize=500, stretch="always")
        content.add(editor, minsize=380, stretch="always")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        columns = ("nombre", "modelo", "estrategia", "datos", "activo")
        self.profiles_tree = ttk.Treeview(
            list_frame, columns=columns, show="headings", style="Dark.Treeview", height=6
        )
        cabeceras_perfiles = {
            "nombre": "Perfil", "modelo": "Modelo", "estrategia": "Estrategia",
            "datos": "Datos", "activo": "Activo",
        }
        for column, text in cabeceras_perfiles.items():
            self.profiles_tree.heading(column, text=text)
            self.profiles_tree.column(column, width=145 if column != "nombre" else 190)
        self.profiles_tree.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.profiles_tree.bind("<<TreeviewSelect>>", lambda _event: self._select_profile())

        self.profile_form = {
            "model": tk.StringVar(value="Automático (Broker)"),
            "strategy": tk.StringVar(value=STRATEGY_LABELS["single"]),
            "classification": tk.StringVar(value=CLASSIFICATION_LABELS["local_only"]),
            "long_context": tk.StringVar(value=LONG_CONTEXT_LABELS["fail"]),
            "compression": tk.StringVar(value=COMPRESSION_LABELS[""]), "max_cost": tk.StringVar(value="0.05"),
            "max_output_tokens": tk.StringVar(value="8000"),
            "human_review": tk.BooleanVar(value=False),
        }
        fields = [
            ("Modelo", "model", ("Automático (Broker)",)),
            ("Método de procesamiento", "strategy", tuple(STRATEGY_LABELS.values())),
            ("Privacidad", "classification", tuple(CLASSIFICATION_LABELS.values())),
            ("Documentos extensos", "long_context", tuple(LONG_CONTEXT_LABELS.values())),
            ("Uso del contexto", "compression", tuple(COMPRESSION_LABELS.values())),
        ]
        self.profile_combos = {}
        for row, (label, key, values) in enumerate(fields):
            tk.Label(editor, text=label, bg=self.colors["surface"], fg=self.colors["muted"],
                     font=("Segoe UI", 9)).grid(row=row, column=0, sticky="w", pady=6)
            combo = ttk.Combobox(editor, textvariable=self.profile_form[key], values=values,
                                 state="readonly", width=27, style="Dark.TCombobox")
            combo.grid(row=row, column=1, sticky="ew", padx=(12, 0), pady=6)
            self.profile_combos[key] = combo
        tk.Label(editor, text="Longitud máxima de la respuesta", bg=self.colors["surface"], fg=self.colors["muted"],
                 font=("Segoe UI", 9)).grid(row=5, column=0, sticky="w", pady=6)
        ttk.Entry(editor, textvariable=self.profile_form["max_output_tokens"], width=27, style="Dark.TEntry").grid(
            row=5, column=1, sticky="ew", padx=(12, 0), pady=6
        )
        tk.Label(editor, text="Presupuesto por documento (USD)", bg=self.colors["surface"], fg=self.colors["muted"],
                 font=("Segoe UI", 9)).grid(row=6, column=0, sticky="w", pady=6)
        ttk.Entry(editor, textvariable=self.profile_form["max_cost"], width=27, style="Dark.TEntry").grid(
            row=6, column=1, sticky="ew", padx=(12, 0), pady=6
        )
        ttk.Checkbutton(editor, text="Exigir revisión humana antes de publicar",
                        variable=self.profile_form["human_review"], style="Dark.TCheckbutton").grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(10, 6)
        )
        tk.Label(
            editor,
            text=(
                "La privacidad determina dónde puede procesarse el contenido. "
                "Los cambios solo afectan a documentos nuevos y no alteran la biblioteca existente."
            ),
            bg=self.colors["surface"], fg=self.colors["muted"], font=("Segoe UI", 9), wraplength=430,
            justify="left",
        ).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(8, 14))
        self.save_profile_button = ttk.Button(
            editor, text="Guardar política", style="Accent.TButton", command=self._save_profile
        )
        self.edit_prompt_button = ttk.Button(
            editor, text="Editar instrucciones de extracción…", style="Secondary.TButton",
            command=self._open_prompt_editor,
        )
        self.edit_prompt_button.grid(row=9, column=0, sticky="w")
        self.save_profile_button.grid(row=9, column=1, sticky="e")
        self.save_profile_button.state(["disabled"])
        self.edit_prompt_button.state(["disabled"])
        self._loading_profile = False
        self._profile_dirty = False
        self._profile_prompts = {
            "system_prompt": "", "user_prompt": "", "chunk_prompt": "", "synthesis_prompt": "",
        }
        for profile_variable in self.profile_form.values():
            profile_variable.trace_add("write", self._mark_profile_dirty)
        editor.columnconfigure(1, weight=1)

    def _refresh_profiles(self) -> None:
        profiles = self.snapshots.profiles()
        self._profile_items = {item.profile_id: item for item in profiles}
        self._replace_tree(
            self.profiles_tree,
            [(str(item.profile_id), (item.name, item.preferred_model or "Automático",
              _label_for(STRATEGY_LABELS, item.execution_strategy),
              _label_for(CLASSIFICATION_LABELS, item.data_classification),
              "sí" if item.enabled else "no"))
             for item in profiles],
        )
        if profiles and self._selected_profile_id is None:
            first_id = str(profiles[0].profile_id)
            self.profiles_tree.selection_set(first_id)
            self.profiles_tree.focus(first_id)
            self._select_profile()

    def _choose_folder(self, variable: tk.StringVar) -> None:
        selected = filedialog.askdirectory(parent=self, initialdir=variable.get() or None)
        if selected:
            variable.set(selected)

    def _save_paths(self) -> None:
        try:
            self._path_store.save(
                data_root=self.paths_var.get(),
                inbox=self.inbox_path_var.get(),
                obsidian_vault=self.results_path_var.get(),
            )
        except (OSError, ValueError) as error:
            messagebox.showerror("No se pudieron guardar las carpetas", str(error), parent=self)
            return
        self.path_status_var.set(
            "Carpetas guardadas. Se usarán al volver a abrir la aplicación; la conexión al Broker no necesita reinicio."
        )
        self.status_var.set("Ubicaciones guardadas para el próximo inicio.")

    def _broker_credential_status(self) -> str:
        if self.connection_store.has_stored_token():
            return "Credencial protegida para este usuario de Windows. Déjala vacía para conservarla."
        if self.runtime.broker_worker.settings.admin_token:
            return "Credencial activa desde el entorno. Déjala vacía para conservarla."
        return "Falta la credencial. Pega el token actual del Broker."

    def _save_broker_connection(self) -> None:
        token = self.broker_token_var.get().strip() or None
        try:
            self.connection_store.save(self.broker_url_var.get(), token=token)
        except (BrokerConnectionError, OSError) as error:
            messagebox.showerror("No se pudo guardar la conexión", str(error), parent=self)
            return
        self._reload_broker_connection()
        self.broker_token_var.set("")
        self.broker_credential_var.set(self._broker_credential_status())
        self.status_var.set("Conexión guardada y aplicada. Comprobando el Broker…")
        messagebox.showinfo(
            "Conexión guardada",
            "La dirección y la credencial ya están activas. No hace falta reiniciar Knowledge Orchestrator.",
            parent=self,
        )

    def _clear_broker_token(self) -> None:
        if not messagebox.askyesno(
            "Eliminar credencial",
            "Se eliminará el token protegido de este equipo. ¿Quieres continuar?",
            parent=self,
        ):
            return
        try:
            self.connection_store.clear_token()
        except OSError as error:
            messagebox.showerror("No se pudo eliminar la credencial", str(error), parent=self)
            return
        self._reload_broker_connection()
        self.broker_token_var.set("")
        self.broker_credential_var.set(self._broker_credential_status())
        self.status_var.set("Credencial protegida eliminada y conexión actualizada.")

    def _reload_broker_connection(self) -> None:
        """Aplica URL/token guardados conservando los tiempos configurados del runtime."""

        stored = load_broker_settings(self.runtime.paths)
        current = self.runtime.broker_worker.settings
        self.runtime.broker_worker.reconfigure(
            replace(current, base_url=stored.base_url, admin_token=stored.admin_token)
        )

    def _refresh_capabilities(self) -> None:
        capabilities = self.runtime.broker_worker.capabilities_snapshot()
        strategies = available_profile_strategies(capabilities)
        self.profile_combos["strategy"].configure(values=tuple(STRATEGY_LABELS[value] for value in strategies))
        # Sin capacidades publicadas se ofrece todo y decide el Broker: mejor
        # que esconder una opción que sí existe.
        admite_troceo = not capabilities or capabilities.get("long_context_map_reduce")
        self.profile_combos["long_context"].configure(
            values=(
                tuple(LONG_CONTEXT_LABELS.values())
                if admite_troceo
                else (LONG_CONTEXT_LABELS["fail"],)
            )
        )
        if not capabilities:
            self.capabilities_var.set("No hay capacidades publicadas. El Broker validará las peticiones nuevas.")
            return
        lanes = ", ".join(capabilities.get("work_lanes") or ["inference"])
        self.capabilities_var.set(
            f"Contrato {capabilities.get('contract_version', '?')} · Carriles: {lanes} · "
            f"Métodos disponibles: {', '.join(STRATEGY_LABELS[value] for value in strategies)}"
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
        current = self.runtime.profiles.get_profile(profile_id)
        self._loading_profile = True
        models = ["Automático (Broker)", *self.snapshots.model_names()]
        if item.preferred_model and item.preferred_model not in models:
            models.append(item.preferred_model)
        self.profile_combos["model"].configure(values=models)
        self.profile_form["model"].set(item.preferred_model or "Automático (Broker)")
        self.profile_form["strategy"].set(_label_for(STRATEGY_LABELS, item.execution_strategy))
        self.profile_form["classification"].set(_label_for(CLASSIFICATION_LABELS, item.data_classification))
        self.profile_form["long_context"].set(_label_for(LONG_CONTEXT_LABELS, item.long_context))
        self.profile_form["compression"].set(_label_for(COMPRESSION_LABELS, item.prompt_compression))
        self.profile_form["max_cost"].set(str(item.max_cost_usd))
        self.profile_form["max_output_tokens"].set(str(current.max_output_tokens))
        self.profile_form["human_review"].set(item.human_review_required)
        self._profile_prompts = {
            "system_prompt": current.system_prompt,
            "user_prompt": current.user_prompt,
            "chunk_prompt": current.chunk_prompt,
            "synthesis_prompt": current.synthesis_prompt,
        }
        self._loading_profile = False
        self._profile_dirty = False
        self._sync_profile_buttons()
        self.edit_prompt_button.state(["!disabled"])

    def _mark_profile_dirty(self, *_args: object) -> None:
        if self._loading_profile or self._selected_profile_id is None:
            return
        self._profile_dirty = True
        self._sync_profile_buttons()

    def _sync_profile_buttons(self) -> None:
        if profile_save_enabled(self._selected_profile_id, dirty=self._profile_dirty):
            self.save_profile_button.state(["!disabled"])
        else:
            self.save_profile_button.state(["disabled"])

    def _open_prompt_editor(self) -> None:
        if self._selected_profile_id is None:
            return
        dialog = tk.Toplevel(self)
        dialog.title("Instrucciones de extracción y apuntes")
        dialog.geometry("920x680")
        dialog.minsize(700, 500)
        dialog.transient(self)
        dialog.configure(background=self.colors["surface"])
        tk.Label(
            dialog,
            text="Estas instrucciones controlan la limpieza, extracción y redacción de los apuntes.",
            bg=self.colors["surface"], fg=self.colors["muted"], font=("Segoe UI", 10), anchor="w",
        ).pack(fill="x", padx=18, pady=(16, 10))
        notebook = ttk.Notebook(dialog)
        notebook.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        labels = {
            "system_prompt": "Criterios generales",
            "user_prompt": "Documento completo",
            "chunk_prompt": "Fragmentos largos",
            "synthesis_prompt": "Síntesis final",
        }
        editors: dict[str, tk.Text] = {}
        for key, label in labels.items():
            frame = tk.Frame(notebook, bg=self.colors["surface"])
            notebook.add(frame, text=label)
            text = tk.Text(
                frame, wrap="word", undo=True, bg=self.colors["raised"], fg=self.colors["text"],
                insertbackground=self.colors["text"], relief="flat", padx=12, pady=12, font=("Segoe UI", 10),
            )
            text.insert("1.0", self._profile_prompts[key])
            text.pack(fill="both", expand=True)
            editors[key] = text
        actions = tk.Frame(dialog, bg=self.colors["surface"])
        actions.pack(fill="x", padx=18, pady=(0, 16))
        ttk.Button(actions, text="Cancelar", style="Secondary.TButton", command=dialog.destroy).pack(side="right")

        def apply_prompts() -> None:
            self._profile_prompts = {key: editor.get("1.0", "end-1c") for key, editor in editors.items()}
            self._profile_dirty = True
            self._sync_profile_buttons()
            dialog.destroy()

        ttk.Button(
            actions, text="Aplicar cambios", style="Accent.TButton", command=apply_prompts
        ).pack(side="right", padx=(0, 8))
        dialog.grab_set()

    def _save_profile(self) -> None:
        if self._selected_profile_id is None:
            return
        try:
            max_cost = float(self.profile_form["max_cost"].get())
            max_output_tokens = int(self.profile_form["max_output_tokens"].get())
            current = self.runtime.profiles.get_profile(self._selected_profile_id)
            capabilities = self.runtime.broker_worker.capabilities_snapshot()
            strategy = _value_for(STRATEGY_LABELS, self.profile_form["strategy"].get())
            if capabilities and strategy not in available_profile_strategies(capabilities):
                raise ValueError(f"El Broker actual no ofrece la estrategia {strategy}")
            long_context = _value_for(LONG_CONTEXT_LABELS, self.profile_form["long_context"].get())
            if long_context == "map_reduce" and capabilities and not capabilities.get("long_context_map_reduce"):
                raise ValueError("El Broker actual no permite procesar documentos extensos por bloques")
            updated = replace(
                current,
                preferred_model=(
                ""
                if self.profile_form["model"].get() == "Automático (Broker)"
                else self.profile_form["model"].get()
            ),
                execution_strategy=strategy,
                data_classification=_value_for(
                    CLASSIFICATION_LABELS, self.profile_form["classification"].get()
                ),
                long_context=long_context,
                prompt_compression=(
                    None
                    if _value_for(COMPRESSION_LABELS, self.profile_form["compression"].get()) == ""
                    else _value_for(COMPRESSION_LABELS, self.profile_form["compression"].get())
                ),
                max_cost_usd=max_cost,
                max_output_tokens=max_output_tokens,
                human_review_required=bool(self.profile_form["human_review"].get()),
                system_prompt=self._profile_prompts["system_prompt"],
                user_prompt=self._profile_prompts["user_prompt"],
                chunk_prompt=self._profile_prompts["chunk_prompt"],
                synthesis_prompt=self._profile_prompts["synthesis_prompt"],
            )
            saved = self.runtime.profiles.save_profile(updated)
        except (TypeError, ValueError, RuntimeError) as error:
            messagebox.showerror("No se pudo guardar la política", str(error), parent=self)
            return
        self.status_var.set(f"Perfil {saved.name} actualizado. La política se aplicará a documentos nuevos.")
        self._profile_dirty = False
        self._sync_profile_buttons()
        self._refresh_profiles()
