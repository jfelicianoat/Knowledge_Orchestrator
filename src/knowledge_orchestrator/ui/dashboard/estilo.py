"""Paleta y estilos ttk del panel.

THESIS: el trabajo activo es el producto; se rechaza la cuadrícula de métricas
como pantalla principal.
OWN-WORLD: superficies grafito, divisores precisos, texto claro y cian reservado
para acción, selección y actividad.

La paleta vive aquí y no en cada vista para que un cambio de superficie sea
un cambio en un sitio. Las vistas la leen como `self.colors`.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class EstiloMixin(tk.Tk):
    """Colores del panel y configuración de los estilos ttk."""

    refresh_ms = 2000
    colors = {
        "root": "#0b1115",
        "header": "#0a0f13",
        "surface": "#11191e",
        "raised": "#182228",
        "border": "#2b3941",
        "text": "#f2f6f8",
        "muted": "#aebbc2",
        "accent": "#25c5df",
        "accent_dark": "#123649",
        "success": "#42d17d",
        "warning": "#f5ad2d",
        "error": "#ff646d",
    }

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Dark.TFrame", background=self.colors["surface"])
        style.configure("Raised.TFrame", background=self.colors["raised"])
        style.configure(
            "Dark.TLabel", background=self.colors["surface"], foreground=self.colors["text"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Muted.TLabel", background=self.colors["surface"], foreground=self.colors["muted"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "Title.TLabel", background=self.colors["surface"], foreground=self.colors["text"],
            font=("Segoe UI Semibold", 18),
        )
        style.configure(
            "Section.TLabel", background=self.colors["surface"], foreground=self.colors["text"],
            font=("Segoe UI Semibold", 11),
        )
        style.configure(
            "Accent.TButton", background=self.colors["accent"], foreground="#061015",
            bordercolor=self.colors["accent"], padding=(16, 9), font=("Segoe UI Semibold", 10),
        )
        style.map("Accent.TButton", background=[("active", "#55d8ea"), ("disabled", "#35515a")])
        style.configure(
            "Secondary.TButton", background=self.colors["raised"], foreground=self.colors["text"],
            bordercolor=self.colors["border"], padding=(14, 9), font=("Segoe UI", 10),
        )
        style.map("Secondary.TButton", background=[("active", "#223038")])
        style.configure(
            "Danger.TButton", background="#311b20", foreground="#ff9aa0",
            bordercolor="#7b3037", padding=(14, 9), font=("Segoe UI", 10),
        )
        style.configure(
            "Dark.TEntry", fieldbackground=self.colors["raised"], foreground=self.colors["text"],
            insertcolor=self.colors["text"], bordercolor=self.colors["border"], padding=8,
        )
        style.configure(
            "Dark.TCombobox", fieldbackground=self.colors["raised"], background=self.colors["raised"],
            foreground=self.colors["text"], arrowcolor=self.colors["muted"], padding=6,
        )
        style.map("Dark.TCombobox", fieldbackground=[("readonly", self.colors["raised"])])
        style.configure(
            "Dark.Treeview", background=self.colors["surface"], fieldbackground=self.colors["surface"],
            foreground=self.colors["text"], bordercolor=self.colors["border"], rowheight=48,
            font=("Segoe UI", 10),
        )
        style.map(
            "Dark.Treeview",
            background=[("selected", self.colors["accent_dark"])],
            foreground=[("selected", self.colors["text"])],
        )
        style.configure(
            "Dark.Treeview.Heading", background=self.colors["raised"], foreground=self.colors["muted"],
            bordercolor=self.colors["border"], padding=(8, 9), font=("Segoe UI Semibold", 9),
        )
        style.map("Dark.Treeview.Heading", background=[("active", "#223038")])
        style.configure(
            "Dark.TCheckbutton", background=self.colors["surface"], foreground=self.colors["text"],
            indicatorbackground=self.colors["raised"], indicatorforeground=self.colors["accent"],
        )
