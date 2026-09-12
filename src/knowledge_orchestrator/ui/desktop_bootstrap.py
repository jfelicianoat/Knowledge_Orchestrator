"""Carga diferida del escritorio, antes de crear intérpretes Tcl/Tk."""
from __future__ import annotations

import sys
from pathlib import Path


def _prepare_windows_tcl() -> None:
    # Verified on CPython 3.14.0 with its bundled Tcl 8.6.15. Initializing after
    # _tkinter is imported is too late; keep other runtimes and frozen builds intact.
    if (sys.platform != 'win32' or sys.version_info[:3] != (3, 14, 0)
            or getattr(sys, 'frozen', False) or '_tkinter' in sys.modules):
        return
    library = Path(sys.base_prefix) / 'DLLs' / 'tcl86t.dll'
    if not library.is_file():
        return
    import ctypes

    tcl = ctypes.WinDLL(str(library))
    initialize = tcl.Tcl_FindExecutable
    initialize.argtypes = [ctypes.c_char_p]
    initialize.restype = None
    initialize(sys.executable.encode('utf-8'))


def load_dashboard():
    _prepare_windows_tcl()
    from knowledge_orchestrator.ui.dashboard import run_dashboard

    return run_dashboard
