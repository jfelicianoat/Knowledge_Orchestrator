"""Vista «Configuración»: la política que se aplica a los trabajos nuevos.

Las estrategias que se ofrecen salen de lo que el Broker dice admitir, no de
una lista fija: ofrecer una estrategia que el Broker no tiene es prometer
algo que fallará al primer trabajo.
"""
from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, ttk

from knowledge_orchestrator.runtime import OrchestratorRuntime
from knowledge_orchestrator.ui.dashboard.temas import TemasMixin


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


class ConfiguracionMixin(TemasMixin):
    """Raíz de datos, capacidades del Broker y edición de perfiles."""

    def _build_config(self) -> None:
        page = self._new_page("config")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)
        self._page_heading(page, "Configuración", "Ajusta la política aplicada a los trabajos nuevos.")
        self.paths_var = tk.StringVar(value=data_root_label(self.runtime))
        info = tk.Frame(page, bg=self.colors["raised"], highlightbackground=self.colors["border"], highlightthickness=1)
        info.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 14))
        tk.Label(info, text="Raíz de datos", bg=self.colors["raised"], fg=self.colors["muted"],
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 4))
        tk.Label(info, textvariable=self.paths_var, bg=self.colors["raised"], fg=self.colors["text"],
                 font=("Consolas", 9)).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 8))
        self.capabilities_var = tk.StringVar(value="Esperando negociación con el Broker…")
        tk.Label(info, textvariable=self.capabilities_var, bg=self.colors["raised"], fg=self.colors["muted"],
                 font=("Segoe UI", 9), wraplength=1250, justify="left").grid(
            row=2, column=0, sticky="ew", padx=14, pady=(0, 12)
        )
        info.columnconfigure(0, weight=1)

        content = tk.PanedWindow(page, orient="horizontal", bg=self.colors["border"], sashwidth=2, bd=0)
        content.grid(row=3, column=0, sticky="nsew", padx=24, pady=(0, 24))
        list_frame = tk.Frame(content, bg=self.colors["surface"])
        editor = tk.Frame(content, bg=self.colors["surface"])
        content.add(list_frame, minsize=500, stretch="always")
        content.add(editor, minsize=380, stretch="always")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        columns = ("nombre", "modelo", "estrategia", "datos", "activo")
        self.profiles_tree = ttk.Treeview(
            list_frame, columns=columns, show="headings", style="Dark.Treeview", height=15
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
            "model": tk.StringVar(value="Automático (Broker)"), "strategy": tk.StringVar(value="single"),
            "classification": tk.StringVar(value="local_only"), "long_context": tk.StringVar(value="fail"),
            "compression": tk.StringVar(value="default del Broker"), "max_cost": tk.StringVar(value="0.05"),
            "human_review": tk.BooleanVar(value=False),
        }
        fields = [
            ("Modelo", "model", ("Automático (Broker)",)),
            ("Estrategia", "strategy", ("single", "mixture_of_agents", "auto")),
            ("Clasificación", "classification", ("public", "internal", "confidential", "local_only")),
            ("Contexto largo", "long_context", ("fail", "map_reduce")),
            ("Compresión", "compression", ("default del Broker", "off", "light", "medium", "aggressive")),
        ]
        self.profile_combos = {}
        for row, (label, key, values) in enumerate(fields):
            tk.Label(editor, text=label, bg=self.colors["surface"], fg=self.colors["muted"],
                     font=("Segoe UI", 9)).grid(row=row, column=0, sticky="w", pady=6)
            combo = ttk.Combobox(editor, textvariable=self.profile_form[key], values=values,
                                 state="readonly", width=27, style="Dark.TCombobox")
            combo.grid(row=row, column=1, sticky="ew", padx=(12, 0), pady=6)
            self.profile_combos[key] = combo
        tk.Label(editor, text="Presupuesto por tarea (USD)", bg=self.colors["surface"], fg=self.colors["muted"],
                 font=("Segoe UI", 9)).grid(row=5, column=0, sticky="w", pady=6)
        ttk.Entry(editor, textvariable=self.profile_form["max_cost"], width=27, style="Dark.TEntry").grid(
            row=5, column=1, sticky="ew", padx=(12, 0), pady=6
        )
        ttk.Checkbutton(editor, text="Exigir revisión humana antes de publicar",
                        variable=self.profile_form["human_review"], style="Dark.TCheckbutton").grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(10, 6)
        )
        tk.Label(
            editor,
            text=(
                "La clasificación controla si el contenido puede salir a la nube. "
                "Los cambios solo afectan a tareas nuevas."
            ),
            bg=self.colors["surface"], fg=self.colors["muted"], font=("Segoe UI", 9), wraplength=430,
            justify="left",
        ).grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 14))
        self.save_profile_button = ttk.Button(
            editor, text="Guardar política", style="Accent.TButton", command=self._save_profile
        )
        self.save_profile_button.grid(row=8, column=1, sticky="e")
        self.save_profile_button.state(["disabled"])
        editor.columnconfigure(1, weight=1)

    def _refresh_profiles(self) -> None:
        profiles = self.snapshots.profiles()
        self._profile_items = {item.profile_id: item for item in profiles}
        self._replace_tree(
            self.profiles_tree,
            [(str(item.profile_id), (item.name, item.preferred_model or "Automático",
              item.execution_strategy, item.data_classification, "sí" if item.enabled else "no"))
             for item in profiles],
        )

    def _refresh_capabilities(self) -> None:
        capabilities = self.runtime.broker_worker.capabilities_snapshot()
        strategies = available_profile_strategies(capabilities)
        self.profile_combos["strategy"].configure(values=strategies)
        # Sin capacidades publicadas se ofrece todo y decide el Broker: mejor
        # que esconder una opción que sí existe.
        admite_troceo = not capabilities or capabilities.get("long_context_map_reduce")
        self.profile_combos["long_context"].configure(
            values=("fail", "map_reduce") if admite_troceo else ("fail",)
        )
        if not capabilities:
            self.capabilities_var.set("No hay capacidades publicadas. El Broker validará las peticiones nuevas.")
            return
        lanes = ", ".join(capabilities.get("work_lanes") or ["inference"])
        self.capabilities_var.set(
            f"Contrato {capabilities.get('contract_version', '?')} · Carriles: {lanes} · "
            f"Estrategias: {', '.join(strategies)}"
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
                ""
                if self.profile_form["model"].get() == "Automático (Broker)"
                else self.profile_form["model"].get()
            ),
                execution_strategy=strategy,
                data_classification=self.profile_form["classification"].get(),
                long_context=long_context,
                prompt_compression=(
                None
                if self.profile_form["compression"].get() == "default del Broker"
                else self.profile_form["compression"].get()
            ),
                max_cost_usd=max_cost,
                human_review_required=bool(self.profile_form["human_review"].get()),
            )
            saved = self.runtime.profiles.save_profile(updated)
        except (TypeError, ValueError, RuntimeError) as error:
            messagebox.showerror("No se pudo guardar la política", str(error), parent=self)
            return
        self.status_var.set(f"Perfil {saved.name} actualizado. La política se aplicará a las tareas nuevas.")
        self._refresh_profiles()
