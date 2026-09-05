"""Arranque del runtime fuera del hilo de Tk para que la ventana aparezca enseguida."""
from __future__ import annotations

import threading

from knowledge_orchestrator.runtime import OrchestratorRuntime


class RuntimeStartup:
    """Coordina un arranque lento y garantiza un cierre limpio durante la recuperación."""

    def __init__(self, runtime: OrchestratorRuntime) -> None:
        self.runtime = runtime
        self.error: Exception | None = None
        self._done = threading.Event()
        self._cancelled = threading.Event()
        self._runtime_started = threading.Event()
        self._stop_lock = threading.Lock()
        self._stop_requested = False
        self._thread: threading.Thread | None = None

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="runtime-startup", daemon=True)
        self._thread.start()

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    def cancel(self) -> None:
        self._cancelled.set()
        if self._runtime_started.is_set():
            self._stop_runtime_once()

    def _run(self) -> None:
        try:
            self.runtime.start()
        except Exception as error:
            self.error = error
            try:
                self.runtime.stop()
            except Exception:
                pass
        else:
            self._runtime_started.set()
            if self._cancelled.is_set():
                self._stop_runtime_once()
        finally:
            self._done.set()

    def _stop_runtime_once(self) -> None:
        with self._stop_lock:
            if self._stop_requested:
                return
            self._stop_requested = True
        self.runtime.stop()
