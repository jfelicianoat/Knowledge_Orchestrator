"""Lecturas de la ventana fuera del hilo de Tk (26-oct-2026).

La lista de Trabajo llegó a tardar 6–12 s y el refresco la repetía cada 2 s en
el hilo de la ventana: la interfaz no atendía clics. En el refresco periódico
cada lectura devuelve ahora su último resultado y se renueva en un hilo aparte;
la siguiente pasada ya pinta lo nuevo. Fuera del refresco periódico (arranque,
F5, tras una acción del usuario) se lee en el acto, porque quien acaba de actuar
tiene que ver el resultado.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

#: Lecturas distintas que se recuerdan (cada búsqueda en la biblioteca es una).
MAX_CACHED_READS = 64


class BackgroundSnapshots:
    """Envuelve un servicio de solo lectura (UiSnapshotService)."""

    def __init__(self, service: Any) -> None:
        self._service = service
        self._lock = threading.Lock()
        #: clave -> (monotonic al empezar la lectura, valor, error de la última lectura en segundo plano)
        self._cache: dict[tuple, tuple[float, Any, BaseException | None]] = {}
        self._pending: set[tuple] = set()
        self._requests: queue.Queue[tuple | None] = queue.Queue()
        self._periodic = False  # solo lo cambia el hilo de Tk
        self._thread = threading.Thread(target=self._run, name="ui-snapshots", daemon=True)
        self._thread.start()

    @contextmanager
    def periodic(self) -> Iterator[None]:
        self._periodic = True
        try:
            yield
        finally:
            self._periodic = False

    def close(self) -> None:
        self._requests.put(None)

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._service, name)
        if not callable(attribute):
            return attribute

        def read(*args: Any, **kwargs: Any) -> Any:
            key = (name, args, tuple(sorted(kwargs.items())))
            if self._periodic:
                with self._lock:
                    cached = self._cache.get(key)
                    if cached is not None:
                        if key not in self._pending:
                            self._pending.add(key)
                            self._requests.put((key, attribute, args, kwargs))
                        started, value, error = cached
                        if error is not None:
                            # El fallo se anuncia una vez, como antes: el refresco lo registra y avisa.
                            self._cache[key] = (started, value, None)
                            raise error
                        return value
            started = time.monotonic()
            value = attribute(*args, **kwargs)
            self._store(key, started, value)
            return value

        return read

    def _store(self, key: tuple, started: float, value: Any, error: BaseException | None = None) -> None:
        with self._lock:
            current = self._cache.get(key)
            if current is not None and current[0] > started:
                return  # ya hay una lectura más reciente (p. ej. la de una acción del usuario)
            if error is not None:
                if current is None:
                    return
                value = current[1]  # se sigue mostrando lo último bueno
            self._cache.pop(key, None)
            self._cache[key] = (started, value, error)
            while len(self._cache) > MAX_CACHED_READS:
                self._cache.pop(next(iter(self._cache)))

    def _run(self) -> None:
        while True:
            request = self._requests.get()
            if request is None:
                return
            key, attribute, args, kwargs = request
            started = time.monotonic()
            try:
                value = attribute(*args, **kwargs)
            except Exception as error:
                logger.exception("Falló una lectura de la vista en segundo plano (%s)", key[0])
                self._store(key, started, None, error)
            else:
                self._store(key, started, value)
            finally:
                with self._lock:
                    self._pending.discard(key)
