"""Comportamiento común de los diálogos propios (auditoría 14-oct I-10, I-13, I-14).

- Todo `Toplevel` transitorio aparece centrado sobre su ventana, no en la esquina de la pantalla.
- Enter activa el botón ttk que tiene el foco, como en cualquier diálogo de Windows.
- `ask_text` sustituye a `simpledialog.askstring`, cuyos botones dicen «OK/Cancel».
"""
from __future__ import annotations

import contextlib
import os
import re
import sys
import threading
import tkinter as tk
from collections.abc import Iterator
from tkinter import ttk


def center_on_parent(dialog: tk.Toplevel) -> None:
    """Coloca el diálogo en el centro de la ventana de la que depende."""

    master = dialog.master.winfo_toplevel() if dialog.master is not None else None
    if master is None or not master.winfo_viewable():
        return
    dialog.update_idletasks()
    width = dialog.winfo_width() if dialog.winfo_ismapped() else dialog.winfo_reqwidth()
    height = dialog.winfo_height() if dialog.winfo_ismapped() else dialog.winfo_reqheight()
    x = master.winfo_rootx() + max(0, (master.winfo_width() - width) // 2)
    y = master.winfo_rooty() + max(0, (master.winfo_height() - height) // 3)
    dialog.geometry(f"+{x}+{y}")


def _place_once(event: tk.Event) -> None:
    dialog = event.widget
    # <Map> también llega de los hijos; solo cuenta el diálogo, y una vez.
    if not isinstance(dialog, tk.Toplevel) or getattr(dialog, "_ko_placed", False):
        return
    dialog._ko_placed = True  # type: ignore[attr-defined]
    if dialog.wm_transient():
        center_on_parent(dialog)


def install_dialog_behaviour(root: tk.Misc) -> None:
    root.bind_class("Toplevel", "<Map>", _place_once, add="+")
    for key in ("<Return>", "<KP_Enter>"):
        root.bind_class("TButton", key, _invoke_focused, add="+")


def _invoke_focused(event: tk.Event) -> None:
    if isinstance(event.widget, ttk.Button):
        event.widget.invoke()


def ask_text(parent: tk.Misc, title: str, prompt: str, *, secret: bool = False, initial: str = "") -> str | None:
    """Pide un texto con «Aceptar/Cancelar»; `None` si se cancela."""

    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent.winfo_toplevel())
    dialog.resizable(False, False)
    body = ttk.Frame(dialog, padding=18)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text=prompt, wraplength=440, justify="left").pack(anchor="w")
    value = tk.StringVar(value=initial)
    entry = ttk.Entry(body, textvariable=value, width=52, show="•" if secret else "")
    entry.pack(fill="x", pady=(8, 14))
    answer: dict[str, str | None] = {"text": None}

    def accept(_event: object = None) -> None:
        answer["text"] = value.get()
        dialog.destroy()

    buttons = ttk.Frame(body)
    buttons.pack(fill="x")
    ttk.Button(buttons, text="Aceptar", style="Accent.TButton", command=accept).pack(side="right")
    ttk.Button(buttons, text="Cancelar", command=dialog.destroy).pack(side="right", padx=(0, 8))
    entry.bind("<Return>", accept)
    dialog.bind("<Escape>", lambda _event: dialog.destroy())
    entry.focus_set()
    dialog.grab_set()
    dialog.wait_window()
    return answer["text"]


def _fix_slashes(text: str) -> str | None:
    """Texto corregido del campo «Nombre», o None si no hay que tocarlo (sin «/» o es una URL)."""

    if "/" not in text or "://" in text:
        return None
    return text.replace("/", "\\")


def chosen_path(raw: str) -> str:
    """Corrige lo que devuelve Tk al escribir una ruta absoluta entre comillas.

    Tk 8.6 antepone la carpeta abierta: «D:/tmp/D:/tmp/nota.md». Se conserva la
    última ruta absoluta.
    """

    drives = list(re.finditer(r"[A-Za-z]:[\\/]", raw))
    return raw[drives[-1].start():] if len(drives) > 1 else raw


@contextlib.contextmanager
def windows_paths_accept_slashes(title: str) -> Iterator[None]:
    """Mientras dure, el campo «Nombre» del diálogo de archivos `title` convierte «/» en «\».

    El diálogo común de Windows (nuevo y clásico) rechaza las rutas tecleadas
    con «/» («El nombre de archivo no es válido»; auditoría 14-oct I-05). No
    admite ganchos desde Tk, así que un hilo corrige el texto según se escribe.
    """

    if sys.platform != "win32":
        yield
        return
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    stop = threading.Event()
    pid = os.getpid()

    def text_of(hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(32768)
        user32.GetWindowTextW(hwnd, buffer, 32768)
        return buffer.value

    def class_of(hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, buffer, 64)
        return buffer.value

    def edits() -> list[int]:
        dialogs: list[int] = []
        owner = wintypes.DWORD()

        def on_window(hwnd: int, _lparam: int) -> bool:
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and class_of(hwnd) == "#32770" and text_of(hwnd) == title:
                dialogs.append(hwnd)
            return True

        user32.EnumWindows(enum_proc(on_window), 0)
        found: list[int] = []

        def on_child(hwnd: int, _lparam: int) -> bool:
            # «Nombre» (archivos) cuelga de un ComboBox; «Carpeta» (selector de carpetas), del propio diálogo.
            parent = class_of(user32.GetParent(hwnd))
            if class_of(hwnd) == "Edit" and parent in {"ComboBox", "#32770"} and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True

        for dialog in dialogs:
            user32.EnumChildWindows(dialog, enum_proc(on_child), 0)
        return found

    def watch() -> None:
        while not stop.wait(0.05):
            for edit in edits():
                fixed = _fix_slashes(text_of(edit))
                if fixed is not None:
                    user32.SendMessageW(edit, 0x000C, 0, fixed)  # WM_SETTEXT
                    user32.SendMessageW(edit, 0x00B1, len(fixed), len(fixed))  # EM_SETSEL: cursor al final

    thread = threading.Thread(target=watch, name="file-dialog-slashes", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)


__all__ = ["ask_text", "center_on_parent", "chosen_path", "install_dialog_behaviour", "windows_paths_accept_slashes"]
