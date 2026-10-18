"""Lo mínimo para que un lector de pantalla siga la interfaz Tk (auditoría 14-oct I-16).

Tk 8.6 no implementa UI Automation: cada control es una ventana Win32 de clase
`TkChild` sin nombre ni tipo, y el foco de Windows se queda en una sola ventana
aunque el foco de Tk cambie. Medido con UIA: «no expone ningún control».

Sin cambiar de toolkit, Windows permite dos cosas que bastan para NVDA/JAWS/Narrador:
- *Dynamic Annotation* de MSAA (`IAccPropServices`): fijar rol, nombre, valor y
  estado de una ventana Win32 ajena. UIA lo refleja (Button «Guardar fuente»).
- Dar el foco Win32 a la ventana del control que tiene el foco de Tk. El teclado
  de Tk sigue funcionando igual (Tab, escribir, Espacio; medido).

Todo es Windows y defensivo: si algo falla, la interfaz sigue como estaba.
"""
from __future__ import annotations

import sys
import tkinter as tk
import uuid
from tkinter import ttk
from typing import Any

ROLE_PUSHBUTTON, ROLE_TEXT, ROLE_STATICTEXT = 0x2B, 0x2A, 0x29
ROLE_CHECKBUTTON, ROLE_RADIOBUTTON, ROLE_COMBOBOX = 0x2C, 0x2D, 0x2E
ROLE_OUTLINE, ROLE_PAGETABLIST, ROLE_SPINBUTTON = 0x23, 0x3C, 0x34
STATE_UNAVAILABLE, STATE_CHECKED, STATE_READONLY, STATE_FOCUSABLE = 0x1, 0x10, 0x40, 0x100000
OBJID_CLIENT, EVENT_OBJECT_VALUECHANGE = 0xFFFFFFFC, 0x800E


def describe(widget: tk.Misc) -> tuple[int, str, str, int] | None:
    """(rol, nombre, valor, estado) MSAA de un control, o None si no es un control interactivo."""

    state = STATE_FOCUSABLE
    try:
        if "disabled" in widget.state():  # type: ignore[attr-defined]
            state |= STATE_UNAVAILABLE
    except (AttributeError, tk.TclError):
        if str(_option(widget, "state")) == "disabled":
            state |= STATE_UNAVAILABLE
    text = str(_option(widget, "text") or "")
    if isinstance(widget, ttk.Combobox):
        return ROLE_COMBOBOX, label_for(widget), widget.get(), state
    if isinstance(widget, (ttk.Spinbox, tk.Spinbox)):
        return ROLE_SPINBUTTON, label_for(widget), widget.get(), state
    if isinstance(widget, (ttk.Entry, tk.Entry)):
        hidden = bool(_option(widget, "show"))
        return ROLE_TEXT, label_for(widget), "" if hidden else widget.get(), state
    if isinstance(widget, (ttk.Checkbutton, tk.Checkbutton)):
        return ROLE_CHECKBUTTON, text, "", state | (STATE_CHECKED if _checked(widget) else 0)
    if isinstance(widget, (ttk.Radiobutton, tk.Radiobutton)):
        return ROLE_RADIOBUTTON, text, "", state | (STATE_CHECKED if _checked(widget) else 0)
    if isinstance(widget, (ttk.Button, tk.Button)):
        return ROLE_PUSHBUTTON, text.strip(), "", state
    if isinstance(widget, ttk.Treeview):
        return ROLE_OUTLINE, label_for(widget) or _heading(widget), _tree_value(widget), state
    if isinstance(widget, ttk.Notebook):
        current = widget.select()
        return ROLE_PAGETABLIST, "Pestañas", str(widget.tab(current, "text")).strip() if current else "", state
    if isinstance(widget, (tk.Frame, ttk.Frame)) and str(_option(widget, "takefocus")) == "1":
        # Entradas de la barra lateral y tarjetas de Inicio: marcos pulsables con icono y textos.
        return ROLE_PUSHBUTTON, _visible_texts(widget), "", state
    if isinstance(widget, tk.Text):
        readonly = str(_option(widget, "state")) == "disabled"
        content = widget.get("1.0", "end-1c")[:4000]
        return (ROLE_STATICTEXT if readonly else ROLE_TEXT), label_for(widget), content, \
            state | (STATE_READONLY if readonly else 0)
    return None


def _option(widget: tk.Misc, name: str) -> Any:
    try:
        return widget.cget(name)
    except tk.TclError:
        return None


def _checked(widget: tk.Misc) -> bool:
    try:
        return bool(widget.instate(["selected"]))  # type: ignore[attr-defined]
    except (AttributeError, tk.TclError):
        variable = _option(widget, "variable")
        on_value = _option(widget, "onvalue")
        return bool(variable) and str(widget.getvar(str(variable))) == str(on_value if on_value is not None else 1)


def _visible_texts(widget: tk.Misc) -> str:
    """Textos de las etiquetas de dentro, sin los glifos de iconos (zona de uso privado de Unicode)."""

    texts: list[str] = []
    for child in widget.winfo_children():
        if isinstance(child, (tk.Label, ttk.Label)):
            text = _without_icons(str(_option(child, "text") or ""))
            if text.strip():
                texts.append(text.strip())
        else:
            nested = _visible_texts(child)
            if nested:
                texts.append(nested)
    return " · ".join(texts)


def _heading(tree: ttk.Treeview) -> str:
    return str(tree.heading("#0", "text") or "Lista")


def _tree_value(tree: ttk.Treeview) -> str:
    item = tree.focus() or next(iter(tree.selection()), "")
    if not item:
        return "Sin elementos" if not tree.get_children() else "Ningún elemento seleccionado"
    parts = [str(tree.item(item, "text") or "")] + [str(value) for value in tree.item(item, "values")]
    return " · ".join(part for part in parts if part.strip())


def label_for(widget: tk.Misc) -> str:
    """Nombre accesible de un campo: su `accessible_name` o la etiqueta con texto más próxima antes de él."""

    explicit = getattr(widget, "accessible_name", None)
    if explicit:
        return str(explicit)
    parent = widget.master
    if parent is None:
        return ""
    siblings = parent.winfo_children()
    cell = _grid_cell(widget)
    if cell is not None:
        # La etiqueta más cercana a la izquierda en la misma fila (varias parejas etiqueta-campo por fila).
        row, column = cell
        candidates = [(c[1], sibling) for sibling in siblings
                      if sibling is not widget and (c := _grid_cell(sibling)) is not None
                      and c[0] == row and c[1] < column and _label_text(sibling)]
        if candidates:
            return _label_text(max(candidates, key=lambda pair: pair[0])[1])
    index = siblings.index(widget) if widget in siblings else 0
    for sibling in reversed(siblings[:index]):
        if _label_text(sibling):
            return _label_text(sibling)
    # Campo dentro de un marco propio (p. ej. el buscador): la etiqueta va en el padre.
    return label_for(parent) if isinstance(parent, (tk.Frame, ttk.Frame)) and len(siblings) <= 3 else ""


def _grid_cell(widget: tk.Misc) -> tuple[int, int] | None:
    try:
        if widget.winfo_manager() == "grid":
            info = widget.grid_info()  # type: ignore[attr-defined]
            return int(info.get("row", -1)), int(info.get("column", -1))
    except (tk.TclError, ValueError):
        pass
    return None


def _label_text(widget: tk.Misc) -> str:
    if isinstance(widget, (tk.Label, ttk.Label)):
        return _without_icons(str(_option(widget, "text") or "")).strip()
    return ""


def _without_icons(text: str) -> str:
    """Quita los glifos de iconos (zona de uso privado de Unicode): NVDA los leía como «\ue721»."""

    return "".join(ch for ch in text if not 0xE000 <= ord(ch) <= 0xF8FF)


class _Annotator:
    """IAccPropServices por ctypes; inerte fuera de Windows o si COM no está disponible."""

    def __init__(self) -> None:
        self.ready = False
        if sys.platform != "win32":
            return
        try:
            self._load()
        except (OSError, AttributeError, ValueError):
            self.ready = False

    def _load(self) -> None:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        class VARIANT(ctypes.Structure):
            _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                        ("r3", ctypes.c_ushort), ("lVal", ctypes.c_longlong), ("pad", ctypes.c_longlong)]

        def guid(text: str) -> Any:
            return GUID.from_buffer_copy(uuid.UUID(text).bytes_le)

        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)
        service = ctypes.c_void_p()
        result = ole32.CoCreateInstance(ctypes.byref(guid("b5f8350b-0548-48b1-a6ee-88bd00b4a5e7")), None, 1,
                                        ctypes.byref(guid("6e26e776-04f0-495d-80e4-3330352e3169")),
                                        ctypes.byref(service))
        if result != 0 or not service:
            return
        vtable = ctypes.cast(ctypes.cast(service, ctypes.POINTER(ctypes.c_void_p))[0],
                             ctypes.POINTER(ctypes.c_void_p))
        prop = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.HWND, wintypes.DWORD, wintypes.DWORD,
                                  GUID, VARIANT)(vtable[6])
        prop_str = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, wintypes.HWND, wintypes.DWORD,
                                      wintypes.DWORD, GUID, wintypes.LPCWSTR)(vtable[7])
        role, state = guid("CB905FF2-7BD1-4C05-B3C8-E6C241364D70"), guid("A8D4D5B0-0A21-42D0-A5C0-514E984F457B")
        name, value = guid("608d3df8-8128-4aa7-a428-f55e49267291"), guid("123fe443-211a-4615-9527-c45a7e93717a")
        user32 = ctypes.windll.user32

        def annotate(hwnd: int, described: tuple[int, str, str, int]) -> None:
            role_id, label, current, flags = described
            prop(service, hwnd, OBJID_CLIENT, 0, role, VARIANT(vt=3, lVal=role_id))
            prop(service, hwnd, OBJID_CLIENT, 0, state, VARIANT(vt=3, lVal=flags))
            prop_str(service, hwnd, OBJID_CLIENT, 0, name, label)
            prop_str(service, hwnd, OBJID_CLIENT, 0, value, current)

        def take_focus(hwnd: int) -> None:
            # Solo con la ventana en primer plano: SetFocus en una ventana inactiva la activaría
            # y la app robaría el foco al refrescarse en segundo plano.
            if user32.GetForegroundWindow() == user32.GetAncestor(hwnd, 2) and user32.GetFocus() != hwnd:
                user32.SetFocus(hwnd)

        def changed(hwnd: int) -> None:
            user32.NotifyWinEvent(EVENT_OBJECT_VALUECHANGE, hwnd, -4, 0)

        self._service = service  # mantiene viva la referencia COM
        self.annotate, self.take_focus, self.changed = annotate, take_focus, changed
        self.ready = True


def install_accessibility(root: tk.Misc) -> bool:
    """Anota cada control al recibir el foco y se lo pasa a Windows. Devuelve si está activo."""

    annotator = _Annotator()
    if not annotator.ready:
        return False

    def refresh(widget: tk.Misc, *, focus: bool) -> None:
        try:
            described = describe(widget)
            if described is None:
                return
            hwnd = widget.winfo_id()
            annotator.annotate(hwnd, described)
            if focus:
                annotator.take_focus(hwnd)
            else:
                annotator.changed(hwnd)
        except tk.TclError:
            pass  # el control se destruyó entre el evento y la lectura

    def on_focus(event: tk.Event) -> None:
        if isinstance(event.widget, tk.Misc) and not isinstance(event.widget, (tk.Tk, tk.Toplevel)):
            refresh(event.widget, focus=True)

    def on_change(event: tk.Event) -> None:
        if isinstance(event.widget, tk.Misc) and event.widget == event.widget.focus_get():
            refresh(event.widget, focus=False)

    root.bind_all("<FocusIn>", on_focus, add="+")
    for sequence in ("<<TreeviewSelect>>", "<<NotebookTabChanged>>", "<<ComboboxSelected>>"):
        root.bind_all(sequence, on_change, add="+")
    for widget_class in ("TCheckbutton", "TRadiobutton", "Checkbutton"):
        root.bind_class(widget_class, "<ButtonRelease-1>", lambda e: e.widget.after_idle(
            lambda: refresh(e.widget, focus=False)), add="+")
        root.bind_class(widget_class, "<KeyRelease-space>", lambda e: refresh(e.widget, focus=False), add="+")
    return True


__all__ = ["describe", "install_accessibility", "label_for"]
