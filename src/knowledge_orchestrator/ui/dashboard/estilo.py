"""Paleta, tipografía, iconos y estilos ttk del panel.

THESIS: el trabajo activo es el producto; se rechaza la cuadrícula de métricas
como pantalla principal.
OWN-WORLD: superficies grafito, divisores precisos, texto claro y cian reservado
para acción, selección y actividad.

La paleta vive aquí y no en cada vista para que un cambio de superficie sea
un cambio en un sitio. Las vistas la leen como `self.colors`.

Los estilos ttk se configuran también sobre las clases base (`TButton`,
`TNotebook`, `Treeview`…) y no solo sobre variantes con nombre: los paneles
de automatización, reversión, Obsidian y los diálogos usan ttk sin estilo y,
sin esto, aparecían en gris claro dentro de una ventana oscura.

El estado nunca depende solo del color: cada etiqueta de estado lleva icono y
texto además del tono.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

FONT = "Segoe UI"
FONT_SEMIBOLD = "Segoe UI Semibold"
MONO = "Cascadia Mono"
ICON_FONT = "Segoe Fluent Icons"

#: Glifos de Segoe Fluent Icons (comparten punto de código con MDL2 Assets).
ICONS = {
    "home": "\uE80F",
    "document": "\uE8A5",
    "review": "\uE9D5",
    "library": "\uE8F1",
    "claims": "\uE8FD",
    "sources": "\uE774",
    "activity": "\uE81C",
    "automation": "\uE943",
    "folder": "\uE8B7",
    "folder_open": "\uE838",
    "settings": "\uE713",
    "add": "\uE710",
    "open": "\uE8A7",
    "error": "\uEA39",
    "warning": "\uE7BA",
    "check": "\uE73E",
    "sync": "\uE895",
    "lock": "\uE72E",
    "clock": "\uE823",
    "search": "\uE721",
    "question": "\uE9CE",
    "pause": "\uE769",
    "play": "\uE768",
    "refresh": "\uE72C",
    "link": "\uE71B",
    "info": "\uE946",
    "cancel": "\uE711",
    "circle": "\uEA3A",
    "dot": "\uEA3B",
}

#: Tono de estado -> (fondo, texto). Coinciden con DESIGN.md.
TONES = {
    "accent": ("#123649", "#25c5df"),
    "success": ("#12291c", "#42d17d"),
    "warning": ("#2f2410", "#f5ad2d"),
    "error": ("#311b20", "#ff646d"),
    "neutral": ("#1f2a31", "#aebbc2"),
}


class EstiloMixin(tk.Tk):
    """Colores del panel, estilos ttk y pequeñas piezas visuales reutilizables."""

    refresh_ms = 2000
    colors = {
        "root": "#0b1115",
        "header": "#0a0f13",
        "sidebar": "#0d1419",
        "surface": "#11191e",
        "raised": "#182228",
        "hover": "#1f2b33",
        "border": "#2b3941",
        "text": "#f2f6f8",
        "muted": "#aebbc2",
        "faint": "#6f7f88",
        "accent": "#25c5df",
        "accent_dark": "#123649",
        "success": "#42d17d",
        "warning": "#f5ad2d",
        "error": "#ff646d",
    }

    def _configure_style(self) -> None:
        c = self.colors
        # Widgets tk clásicos (Text, Listbox, Toplevel de diálogos): el valor
        # explícito de cada vista sigue mandando; esto cubre los que no lo fijan.
        for pattern, value in (
            ("*Toplevel.background", c["surface"]),
            ("*Text.background", c["raised"]), ("*Text.foreground", c["text"]),
            ("*Text.insertBackground", c["text"]), ("*Text.selectBackground", c["accent_dark"]),
            ("*Text.relief", "flat"), ("*Text.highlightThickness", 0),
            ("*Listbox.background", c["raised"]), ("*Listbox.foreground", c["text"]),
            ("*Listbox.selectBackground", c["accent_dark"]), ("*Listbox.selectForeground", c["text"]),
            ("*TCombobox*Listbox.background", c["raised"]), ("*TCombobox*Listbox.foreground", c["text"]),
            ("*TCombobox*Listbox.selectBackground", c["accent_dark"]),
            ("*TCombobox*Listbox.font", (FONT, 10)),
        ):
            self.option_add(pattern, value)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            ".", background=c["surface"], foreground=c["text"], fieldbackground=c["raised"],
            bordercolor=c["border"], lightcolor=c["surface"], darkcolor=c["surface"],
            troughcolor=c["surface"], selectbackground=c["accent_dark"], selectforeground=c["text"],
            insertcolor=c["text"], focuscolor=c["accent"], font=(FONT, 10),
        )
        style.map(".", foreground=[("disabled", c["faint"])])

        # -- Superficies y textos
        style.configure("TFrame", background=c["surface"])
        style.configure("Dark.TFrame", background=c["surface"])
        style.configure("Raised.TFrame", background=c["raised"])
        style.configure("TLabel", background=c["surface"], foreground=c["text"])
        style.configure("Dark.TLabel", background=c["surface"], foreground=c["text"], font=(FONT, 10))
        style.configure("Muted.TLabel", background=c["surface"], foreground=c["muted"], font=(FONT, 9))
        style.configure("Title.TLabel", background=c["surface"], foreground=c["text"], font=(FONT_SEMIBOLD, 18))
        style.configure("Section.TLabel", background=c["surface"], foreground=c["text"], font=(FONT_SEMIBOLD, 11))
        style.configure("TLabelframe", background=c["surface"], bordercolor=c["border"],
                        lightcolor=c["surface"], darkcolor=c["surface"])
        style.configure("TLabelframe.Label", background=c["surface"], foreground=c["text"],
                        font=(FONT_SEMIBOLD, 10))

        # -- Botones: base secundaria, acento para la acción principal
        style.configure("TButton", background=c["raised"], foreground=c["text"], bordercolor=c["border"],
                        lightcolor=c["raised"], darkcolor=c["raised"], padding=(12, 7), font=(FONT, 10))
        style.map("TButton",
                  background=[("disabled", c["surface"]), ("pressed", c["accent_dark"]), ("active", c["hover"])],
                  bordercolor=[("focus", c["accent"])],
                  lightcolor=[("active", c["hover"])], darkcolor=[("active", c["hover"])])
        style.configure("Secondary.TButton", background=c["raised"], foreground=c["text"],
                        bordercolor=c["border"], padding=(14, 9), font=(FONT, 10))
        style.map("Secondary.TButton", background=[("disabled", c["surface"]), ("active", c["hover"])])
        style.configure("Accent.TButton", background=c["accent"], foreground="#061015", bordercolor=c["accent"],
                        lightcolor=c["accent"], darkcolor=c["accent"], padding=(16, 9),
                        font=(FONT_SEMIBOLD, 10))
        style.map("Accent.TButton",
                  background=[("disabled", "#27434b"), ("active", "#55d8ea")],
                  foreground=[("disabled", "#7d959c")],
                  lightcolor=[("active", "#55d8ea")], darkcolor=[("active", "#55d8ea")])
        style.configure("Danger.TButton", background="#311b20", foreground="#ff9aa0", bordercolor="#7b3037",
                        lightcolor="#311b20", darkcolor="#311b20", padding=(14, 9), font=(FONT, 10))
        style.map("Danger.TButton", background=[("disabled", c["surface"]), ("active", "#43232a")],
                  foreground=[("disabled", c["faint"])], bordercolor=[("disabled", c["border"])])
        style.configure("Ghost.TButton", background=c["surface"], foreground=c["accent"], bordercolor=c["surface"],
                        lightcolor=c["surface"], darkcolor=c["surface"], padding=(8, 6), font=(FONT, 10))
        style.map("Ghost.TButton", background=[("active", c["raised"])])

        # -- Campos
        for name in ("TEntry", "Dark.TEntry", "TSpinbox"):
            style.configure(name, fieldbackground=c["raised"], foreground=c["text"], insertcolor=c["text"],
                            bordercolor=c["border"], lightcolor=c["raised"], darkcolor=c["raised"], padding=7)
            style.map(name, bordercolor=[("focus", c["accent"])], lightcolor=[("focus", c["accent"])],
                      fieldbackground=[("disabled", c["surface"])])
        # Buscador: el marco que lo rodea dibuja el borde y el icono.
        style.configure("Search.TEntry", fieldbackground=c["raised"], foreground=c["text"], insertcolor=c["text"],
                        bordercolor=c["raised"], lightcolor=c["raised"], darkcolor=c["raised"], padding=(2, 6))
        style.map("Search.TEntry", bordercolor=[("focus", c["raised"])], lightcolor=[("focus", c["raised"])])
        for name in ("TCombobox", "Dark.TCombobox"):
            style.configure(name, fieldbackground=c["raised"], background=c["raised"], foreground=c["text"],
                            arrowcolor=c["muted"], bordercolor=c["border"], lightcolor=c["raised"],
                            darkcolor=c["raised"], padding=6)
            style.map(name, fieldbackground=[("readonly", c["raised"]), ("disabled", c["surface"])],
                      foreground=[("readonly", c["text"]), ("disabled", c["faint"])],
                      selectbackground=[("readonly", c["raised"])], selectforeground=[("readonly", c["text"])],
                      bordercolor=[("focus", c["accent"])], background=[("active", c["hover"])])
        for name in ("TCheckbutton", "Dark.TCheckbutton", "TRadiobutton"):
            style.configure(name, background=c["surface"], foreground=c["text"],
                            indicatorbackground=c["raised"], indicatorforeground=c["accent"])
            style.map(name, background=[("active", c["surface"])],
                      indicatorbackground=[("selected", c["accent_dark"])])

        # -- Pestañas
        style.configure("TNotebook", background=c["surface"], bordercolor=c["border"], lightcolor=c["surface"],
                        darkcolor=c["surface"], tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", background=c["surface"], foreground=c["muted"], bordercolor=c["border"],
                        lightcolor=c["surface"], darkcolor=c["surface"], padding=(16, 8), font=(FONT, 10))
        style.map("TNotebook.Tab",
                  background=[("selected", c["raised"]), ("active", c["hover"])],
                  foreground=[("selected", c["text"]), ("active", c["text"])],
                  lightcolor=[("selected", c["accent"])])

        # -- Listas: sin marco claro del tema clam, cabeceras discretas
        for name, height, ground in (("Treeview", 34, c["surface"]), ("Dark.Treeview", 48, c["surface"]),
                                     ("Card.Treeview", 46, c["raised"])):
            style.layout(name, [("Treeview.treearea", {"sticky": "nswe"})])
            style.configure(name, background=ground, fieldbackground=ground, foreground=c["text"],
                            bordercolor=ground, lightcolor=ground, darkcolor=ground,
                            rowheight=height, font=(FONT, 10))
            style.map(name, background=[("selected", c["accent_dark"])], foreground=[("selected", c["text"])])
            style.configure(f"{name}.Heading", background=ground, foreground=c["faint"], bordercolor=c["border"],
                            lightcolor=ground, darkcolor=ground, relief="flat", padding=(8, 8),
                            font=(FONT_SEMIBOLD, 9))
            style.map(f"{name}.Heading", background=[("active", c["hover"])], foreground=[("active", c["text"])])

        # -- Barras de desplazamiento finas, sin flechas
        for orient in ("Vertical", "Horizontal"):
            name = f"{orient}.TScrollbar"
            layout: Any = [(f"{orient}.Scrollbar.trough", {"children": [
                (f"{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})], "sticky": "nswe"})]
            style.layout(name, layout)
            style.configure(name, background=c["border"], troughcolor=c["surface"], bordercolor=c["surface"],
                            lightcolor=c["border"], darkcolor=c["border"], arrowsize=10, gripcount=0)
            style.map(name, background=[("active", "#3d4f59")])
        style.configure("TPanedwindow", background=c["surface"])
        style.configure("Sash", sashthickness=6, gripcount=0, background=c["border"], lightcolor=c["border"],
                        bordercolor=c["border"])
        style.configure("TSeparator", background=c["border"])
        style.configure("TProgressbar", background=c["accent"], troughcolor=c["raised"], bordercolor=c["raised"],
                        lightcolor=c["accent"], darkcolor=c["accent"], thickness=6)

    # ---------------------------------------------------------- piezas visuales

    def _card(self, parent: tk.Misc, *, bg: str | None = None, border: str | None = None) -> tk.Frame:
        """Superficie elevada con borde fino: la unidad visual de las vistas."""

        return tk.Frame(
            parent, bg=bg or self.colors["raised"],
            highlightbackground=border or self.colors["border"], highlightthickness=1, bd=0,
        )

    def _text(
        self, parent: tk.Misc, text: str = "", *, size: int = 10, bold: bool = False, color: str = "text",
        bg: str = "surface", anchor: Any = "w", justify: Any = "left", **options: Any,
    ) -> tk.Label:
        return tk.Label(
            parent, text=text, bg=self.colors.get(bg, bg), fg=self.colors.get(color, color),
            font=(FONT_SEMIBOLD if bold else FONT, size), anchor=anchor, justify=justify, **options,
        )

    def _icon(self, parent: tk.Misc, name: str, *, size: int = 14, color: str = "muted",
              bg: str = "surface", **options: object) -> tk.Label:
        return tk.Label(
            parent, text=ICONS.get(name, name), bg=self.colors.get(bg, bg), fg=self.colors.get(color, color),
            font=(ICON_FONT, size), **options,  # type: ignore[arg-type]
        )

    def _pill(self, parent: tk.Misc, text: str = "", *, tone: str = "neutral", icon: str | None = None) -> tk.Label:
        label = tk.Label(parent, font=(FONT_SEMIBOLD, 9), padx=10, pady=4, bd=0)
        self._set_pill(label, text, tone=tone, icon=icon)
        return label

    @staticmethod
    def _set_pill(label: tk.Label, text: str, *, tone: str = "neutral", icon: str | None = None) -> None:
        background, foreground = TONES.get(tone, TONES["neutral"])
        glyph = STATUS_GLYPHS.get(icon or tone, "")
        label.configure(text=f"{glyph}  {text}" if glyph and text else text, bg=background, fg=foreground)


#: Símbolos Unicode que Segoe UI dibuja dentro de listas y etiquetas
#: (Treeview no admite una segunda fuente por celda).
STATUS_GLYPHS = {
    "accent": "●", "success": "✓", "warning": "▲", "error": "✕", "neutral": "○",
    "lock": "▲", "sync": "●", "check": "✓",
}
