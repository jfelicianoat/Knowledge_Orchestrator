"""Vista «Organización»: cómo se clasifica y publica el conocimiento.

Antes solo listaba los temas; para crear uno o cambiar sus palabras clave
había que tocar SQLite a mano. Ahora la página es un maestro-detalle: la
lista con su orden a la izquierda y el formulario del tema elegido a la
derecha, más una prueba de clasificación que dice qué tema recibiría un
documento antes de importarlo.
"""
from __future__ import annotations

import sqlite3
import tkinter as tk
from dataclasses import replace
from tkinter import ttk

from knowledge_orchestrator.domain.models import TopicDefinition
from knowledge_orchestrator.domain.topics import TopicValidationError
from knowledge_orchestrator.services.classification import TopicClassifier
from knowledge_orchestrator.ui.dashboard.biblioteca import BibliotecaMixin

#: `_inbox` se guarda con la posición máxima de SQLite para quedar el último;
#: ese número no significa nada para el usuario.
RESERVED_POSITION = 2_000_000_000
INBOX = "_inbox"

#: Los mensajes de validación del dominio nombran campos internos
#: («keywords», «folder»); aquí se traducen a lo que la persona ve.
VALIDATION_TEXT = {
    "name debe": "El nombre debe tener entre 1 y 100 caracteres.",
    "folder debe": "La carpeta debe ser una ruta relativa dentro de la bóveda, sin «..», "
                   "sin caracteres como < > : \" | ? * y sin nombres reservados de Windows.",
    "un tema clasificable": "Añade al menos una palabra clave: sin ellas ningún documento llegaría a este tema.",
    "keywords debe": "Cada palabra clave debe contener letras o números.",
    "keywords contiene": "Hay palabras clave repetidas (sin distinguir mayúsculas ni acentos).",
    "El perfil predeterminado no existe": "El perfil elegido ya no existe; elige otro.",
    "El perfil predeterminado está deshabilitado":
        "El perfil elegido está desactivado; actívalo en Ajustes o elige otro.",
    "La carpeta del tema escapa": "La carpeta debe quedar dentro de la bóveda.",
}


def topic_order_label(position: int) -> str:
    return "Último (reserva)" if position >= RESERVED_POSITION else str(position)


def parse_keywords(text: str) -> tuple[str, ...]:
    """Palabras clave separadas por comas o saltos de línea, sin vacías."""

    return tuple(part.strip() for part in text.replace("\n", ",").split(",") if part.strip())


def topic_error_text(error: Exception) -> str:
    message = str(error)
    if isinstance(error, sqlite3.IntegrityError):
        return "Ya existe un tema con ese nombre."
    return next((text for prefix, text in VALIDATION_TEXT.items() if message.startswith(prefix)), message)


class TemasMixin(BibliotecaMixin):
    """Listado de temas, su edición y la prueba de clasificación."""

    def _build_topics(self) -> None:
        c = self.colors
        page = self._new_page("topics")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        self._page_heading(
            page,
            "Organización",
            "Cómo se clasifica el conocimiento en carpetas y qué perfil de procesamiento usa cada tema.",
        )
        info = self._card(page)
        info.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 14))
        info.columnconfigure(1, weight=1)
        self._icon(info, "info", size=15, color="accent", bg="raised").grid(row=0, column=0, sticky="n",
                                                                           padx=(16, 12), pady=14)
        self._text(
            info,
            "Cada documento nuevo se asigna al primer tema activo, por orden, cuyas palabras clave aparecen en su "
            "título, canal o etiquetas; si ninguno coincide, va a «_inbox». El perfil del tema decide modelo, "
            "privacidad y presupuesto.",
            size=9, color="muted", bg="raised", wraplength=900,
        ).grid(row=0, column=1, sticky="ew", pady=14)
        ttk.Button(info, text="Editar perfiles en Ajustes", command=lambda: self._show_page("config")).grid(
            row=0, column=2, padx=16, pady=10)

        body = tk.Frame(page, bg=c["surface"])
        body.grid(row=2, column=0, sticky="nsew", padx=28, pady=(0, 24))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2, minsize=380)
        body.rowconfigure(0, weight=1)

        listing = tk.Frame(body, bg=c["surface"])
        listing.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        listing.columnconfigure(0, weight=1)
        listing.rowconfigure(0, weight=1)
        columns = ("nombre", "carpeta", "perfil", "activo", "pos")
        self.topics_tree = ttk.Treeview(listing, columns=columns, show="headings", selectmode="browse")
        for column, text, width in (("nombre", "Tema", 200), ("carpeta", "Carpeta en la bóveda", 220),
                                    ("perfil", "Perfil de procesamiento", 200), ("activo", "Estado", 100),
                                    ("pos", "Orden", 110)):
            self.topics_tree.heading(column, text=text)
            self.topics_tree.column(column, width=width, minwidth=80)
        self.topics_tree.tag_configure("inactive", foreground=c["faint"])
        self.topics_tree.grid(row=0, column=0, sticky="nsew")
        self.topics_tree.bind("<<TreeviewSelect>>", lambda _event: self._select_topic())
        order = tk.Frame(listing, bg=c["surface"])
        order.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(order, text="Nuevo tema", style="Accent.TButton", command=self._new_topic).pack(side="left")
        self.topic_up_button = ttk.Button(order, text="Subir prioridad", command=lambda: self._move_topic(-1))
        self.topic_up_button.pack(side="left", padx=(12, 6))
        self.topic_down_button = ttk.Button(order, text="Bajar prioridad", command=lambda: self._move_topic(1))
        self.topic_down_button.pack(side="left")

        editor = self._card(body)
        editor.grid(row=0, column=1, sticky="nsew")
        editor.columnconfigure(0, weight=1)
        self.topic_editor_title = tk.StringVar(value="Nuevo tema")
        self._text(editor, textvariable=self.topic_editor_title, size=12, bold=True, bg="raised").grid(
            row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        self.topic_form: dict[str, tk.Variable] = {
            "name": tk.StringVar(), "folder": tk.StringVar(), "profile": tk.StringVar(),
            "enabled": tk.BooleanVar(value=True),
        }
        row = 1
        entries: list[ttk.Entry] = []
        for key, label in (("name", "Nombre"), ("folder", "Carpeta en la bóveda")):
            self._text(editor, label, size=9, color="muted", bg="raised").grid(
                row=row, column=0, sticky="ew", padx=18)
            entry = ttk.Entry(editor, textvariable=self.topic_form[key])
            entry.grid(row=row + 1, column=0, sticky="ew", padx=18, pady=(2, 8))
            entries.append(entry)
            row += 2
        self.topic_name_entry, self.topic_folder_entry = entries
        self._text(
            editor,
            "Cambiar la carpeta solo afecta a los documentos nuevos: las notas ya publicadas se quedan donde están.",
            size=8, color="faint", bg="raised", wraplength=360,
        ).grid(row=row, column=0, sticky="ew", padx=18, pady=(0, 8))
        row += 1
        self._text(editor, "Palabras clave (separadas por comas)", size=9, color="muted", bg="raised").grid(
            row=row, column=0, sticky="ew", padx=18)
        self.topic_keywords_text = tk.Text(
            editor, height=3, wrap="word", bg=c["surface"], fg=c["text"], insertbackground=c["text"],
            relief="flat", highlightthickness=1, highlightbackground=c["border"], font=("Segoe UI", 10),
        )
        self.topic_keywords_text.grid(row=row + 1, column=0, sticky="ew", padx=18, pady=(2, 8))
        row += 2
        self._text(editor, "Perfil de procesamiento", size=9, color="muted", bg="raised").grid(
            row=row, column=0, sticky="ew", padx=18)
        self.topic_profile_combo = ttk.Combobox(editor, textvariable=self.topic_form["profile"], state="readonly")
        self.topic_profile_combo.grid(row=row + 1, column=0, sticky="ew", padx=18, pady=(2, 8))
        row += 2
        ttk.Checkbutton(editor, text="Tema activo (recibe documentos nuevos)", variable=self.topic_form["enabled"],
                        style="Dark.TCheckbutton").grid(row=row, column=0, sticky="w", padx=18, pady=(0, 8))
        row += 1
        self.topic_feedback_var = tk.StringVar(value="")
        self.topic_feedback = self._text(editor, textvariable=self.topic_feedback_var, size=9, color="muted",
                                         bg="raised", wraplength=360)
        self.topic_feedback.grid(row=row, column=0, sticky="ew", padx=18)
        row += 1
        self.topic_save_button = ttk.Button(editor, text="Guardar tema", style="Accent.TButton",
                                            command=self._save_topic_form)
        self.topic_save_button.grid(row=row, column=0, sticky="w", padx=18, pady=(8, 14))
        row += 1

        tk.Frame(editor, bg=c["border"], height=1).grid(row=row, column=0, sticky="ew", padx=18, pady=(4, 12))
        row += 1
        self._text(editor, "Probar clasificación", size=11, bold=True, bg="raised").grid(
            row=row, column=0, sticky="ew", padx=18)
        self._text(editor, "Escribe un título (o canal y etiquetas) y verás qué tema lo recibiría, con los "
                           "temas tal como están guardados.", size=8, color="faint", bg="raised",
                   wraplength=360).grid(row=row + 1, column=0, sticky="ew", padx=18, pady=(2, 6))
        self.topic_probe_var = tk.StringVar()
        self.topic_probe_var.trace_add("write", lambda *_args: self._probe_classification())
        ttk.Entry(editor, textvariable=self.topic_probe_var).grid(row=row + 2, column=0, sticky="ew", padx=18)
        self.topic_probe_result = tk.StringVar(value="—")
        self._text(editor, textvariable=self.topic_probe_result, size=9, bg="raised", wraplength=360).grid(
            row=row + 3, column=0, sticky="ew", padx=18, pady=(6, 16))

        self._topic_items: dict[int, TopicDefinition] = {}
        self._profile_names: dict[str, int] = {}
        self._editing_topic_id: int | None = None
        self._new_topic()

    # ----------------------------------------------------------------- lista

    def _refresh_topics(self) -> None:
        topics = self.runtime.topics.list_topics()
        profiles = {profile.profile_id: profile for profile in self.runtime.profiles.list_profiles()}
        self._topic_items = {topic.topic_id: topic for topic in topics if topic.topic_id is not None}
        self._profile_names = {profile.name: pid for pid, profile in profiles.items()
                               if pid is not None and profile.enabled}
        self.topic_profile_combo.configure(values=sorted(self._profile_names, key=str.casefold))
        self._replace_tree(
            self.topics_tree,
            [(str(topic.topic_id), (
                topic.name, topic.folder,
                profiles[topic.default_profile_id].name if topic.default_profile_id in profiles else "—",
                "✓  Activo" if topic.enabled else "○  Inactivo", topic_order_label(topic.position)))
             for topic in topics],
            tags={str(topic.topic_id): (() if topic.enabled else ("inactive",)) for topic in topics},
        )
        if self._editing_topic_id is not None and self._editing_topic_id in self._topic_items:
            self.topics_tree.selection_set(str(self._editing_topic_id))
        self._sync_topic_order_buttons()
        self._probe_classification()

    def _ordered_topic_ids(self) -> list[int]:
        """Temas clasificables por orden; `_inbox` va siempre al final y no se mueve."""

        ordered = sorted(self._topic_items.values(), key=lambda item: (item.position, item.topic_id or 0))
        return [topic.topic_id for topic in ordered if topic.name != INBOX and topic.topic_id is not None]

    def _sync_topic_order_buttons(self) -> None:
        ordered = self._ordered_topic_ids()
        current = self._editing_topic_id
        index = ordered.index(current) if current in ordered else -1
        self.topic_up_button.state(["!disabled"] if index > 0 else ["disabled"])
        self.topic_down_button.state(["!disabled"] if 0 <= index < len(ordered) - 1 else ["disabled"])

    def _select_topic(self) -> None:
        selection = self.topics_tree.selection()
        if not selection:
            return
        topic = self._topic_items.get(int(selection[0]))
        if topic is None:
            return
        self._load_topic_form(topic)

    def _load_topic_form(self, topic: TopicDefinition) -> None:
        self._editing_topic_id = topic.topic_id
        reserved = topic.name == INBOX
        self.topic_editor_title.set("Tema reservado «_inbox»" if reserved else f"Editar «{topic.name}»")
        self.topic_form["name"].set(topic.name)
        self.topic_form["folder"].set(topic.folder)
        self.topic_form["enabled"].set(topic.enabled)
        profile_name = next((name for name, pid in self._profile_names.items()
                             if pid == topic.default_profile_id), "")
        self.topic_form["profile"].set(profile_name)
        self.topic_keywords_text.delete("1.0", "end")
        self.topic_keywords_text.insert("1.0", ", ".join(topic.keywords))
        # _inbox es la red de seguridad: sin palabras clave y siempre al final.
        # Solo su perfil tiene sentido cambiarlo.
        for widget in (self.topic_name_entry, self.topic_folder_entry):
            widget.state(["disabled"] if reserved else ["!disabled"])
        self.topic_keywords_text.configure(state="disabled" if reserved else "normal")
        self._show_topic_feedback(
            "Recibe lo que no encaja en ningún otro tema. Solo puedes cambiar su perfil." if reserved else "",
            "muted",
        )
        self._sync_topic_order_buttons()

    def _new_topic(self) -> None:
        self._editing_topic_id = None
        self.topics_tree.selection_remove(self.topics_tree.selection())
        self.topic_editor_title.set("Nuevo tema")
        for key in ("name", "folder", "profile"):
            self.topic_form[key].set("")
        self.topic_form["enabled"].set(True)
        for widget in (self.topic_name_entry, self.topic_folder_entry):
            widget.state(["!disabled"])
        self.topic_keywords_text.configure(state="normal")
        self.topic_keywords_text.delete("1.0", "end")
        if self._profile_names:
            self.topic_form["profile"].set(sorted(self._profile_names, key=str.casefold)[0])
        self._show_topic_feedback("", "muted")
        self._sync_topic_order_buttons()

    # -------------------------------------------------------------- escribir

    def _show_topic_feedback(self, message: str, tone: str) -> None:
        self.topic_feedback_var.set(message)
        self.topic_feedback.configure(fg=self.colors.get(tone, self.colors["muted"]))

    def _save_topic_form(self) -> bool:
        """Valida y guarda el formulario. Devuelve si se guardó.

        Los errores se muestran junto al formulario, no en un diálogo: así se
        corrigen sin perder de vista el campo que falla.
        """

        name = str(self.topic_form["name"].get()).strip()
        folder = str(self.topic_form["folder"].get()).strip() or name
        profile_id = self._profile_names.get(str(self.topic_form["profile"].get()))
        if profile_id is None:
            self._show_topic_feedback("Elige un perfil de procesamiento activo.", "error")
            return False
        current = self._topic_items.get(self._editing_topic_id) if self._editing_topic_id is not None else None
        if current is not None and current.name == INBOX:
            topic = replace(current, default_profile_id=profile_id)
        else:
            others = [item.position for item in self._topic_items.values() if item.name != INBOX]
            topic = TopicDefinition(
                name=name,
                folder=folder,
                keywords=parse_keywords(self.topic_keywords_text.get("1.0", "end")),
                position=current.position if current else max(others, default=-1) + 1,
                default_profile_id=profile_id,
                is_updatable=current.is_updatable if current else True,
                obsolescence_days=current.obsolescence_days if current else None,
                auto_review=current.auto_review if current else False,
                enabled=bool(self.topic_form["enabled"].get()),
                topic_id=current.topic_id if current else None,
            )
        try:
            saved = self.runtime.topics.save_topic(topic)
        except (TopicValidationError, ValueError, sqlite3.IntegrityError, OSError) as error:
            self._show_topic_feedback(topic_error_text(error), "error")
            return False
        self._editing_topic_id = saved.topic_id
        self._refresh_topics()
        if saved.topic_id in self._topic_items:
            self._load_topic_form(self._topic_items[saved.topic_id])
        verb = "actualizado" if current else "creado"
        self._show_topic_feedback(f"Tema «{saved.name}» {verb}. Se aplica a los documentos nuevos.", "success")
        self.status_var.set(f"Tema «{saved.name}» {verb}.")
        return True

    def _move_topic(self, step: int) -> None:
        ordered = self._ordered_topic_ids()
        current = self._editing_topic_id
        if current not in ordered:
            return
        index = ordered.index(current)
        target = index + step
        if not 0 <= target < len(ordered):
            return
        ordered[index], ordered[target] = ordered[target], ordered[index]
        try:
            self.runtime.topics.reorder_topics(ordered)
        except ValueError as error:
            self._show_topic_feedback(topic_error_text(error), "error")
            return
        self._refresh_topics()
        self._show_topic_feedback("Prioridad actualizada: los temas de arriba se prueban primero.", "success")

    # ----------------------------------------------------------- clasificar

    def _probe_classification(self) -> None:
        text = self.topic_probe_var.get().strip()
        if not text:
            self.topic_probe_result.set("—")
            return
        topics = list(self._topic_items.values())
        inbox = next((topic for topic in topics if topic.name == INBOX), None)
        if inbox is None:
            self.topic_probe_result.set("Falta el tema reservado «_inbox».")
            return
        chosen = TopicClassifier().classify({"title": text}, topics, inbox)
        if chosen.name == INBOX:
            self.topic_probe_result.set("→ «_inbox»: ninguna palabra clave coincide.")
        else:
            self.topic_probe_result.set(f"→ «{chosen.name}» (carpeta {chosen.folder})")
