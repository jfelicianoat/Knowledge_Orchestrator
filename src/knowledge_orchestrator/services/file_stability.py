from __future__ import annotations

import time
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import BinaryIO

from knowledge_orchestrator.domain.errors import FileLockedError, FileStabilityError, IngestionCancelled


class FileStabilityChecker:
    def __init__(
        self,
        *,
        required_consecutive_checks: int = 3,
        interval_seconds: float = 1.0,
        max_observations: int = 120,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if required_consecutive_checks < 2:
            raise ValueError("Se requieren al menos dos comprobaciones")
        self.required_consecutive_checks = required_consecutive_checks
        self.interval_seconds = interval_seconds
        self.max_observations = max_observations
        self.sleep = sleep

    def wait_until_stable(
        self,
        path: Path,
        *,
        cancel_event: threading.Event | None = None,
    ) -> tuple[int, int]:
        previous: tuple[int, int] | None = None
        consecutive = 0
        for observation in range(self.max_observations):
            if cancel_event and cancel_event.is_set():
                raise IngestionCancelled("Ingesta cancelada durante la comprobación de estabilidad")
            stat = path.stat()
            current = (stat.st_size, stat.st_mtime_ns)
            consecutive = consecutive + 1 if current == previous else 1
            if consecutive >= self.required_consecutive_checks:
                return current
            previous = current
            if observation + 1 < self.max_observations:
                if cancel_event is None:
                    self.sleep(self.interval_seconds)
                elif cancel_event.wait(self.interval_seconds):
                    raise IngestionCancelled("Ingesta cancelada durante la comprobación de estabilidad")
        raise FileStabilityError(
            f"{path} no alcanzó {self.required_consecutive_checks} lecturas consecutivas estables"
        )


def read_bytes_with_lock_retries(
    path: Path,
    *,
    retry_delays: Sequence[float] = (1.0, 2.0, 4.0),
    sleep: Callable[[float], None] = time.sleep,
    opener: Callable[..., BinaryIO] = open,
    cancel_event: threading.Event | None = None,
) -> bytes:
    attempts = len(retry_delays) + 1
    last_error: OSError | None = None
    for attempt in range(attempts):
        if cancel_event and cancel_event.is_set():
            raise IngestionCancelled("Ingesta cancelada durante la espera por bloqueo")
        try:
            with opener(path, "rb") as stream:
                return stream.read()
        except FileNotFoundError:
            raise
        except OSError as error:
            last_error = error
            if attempt == attempts - 1:
                break
            if cancel_event is None:
                sleep(retry_delays[attempt])
            elif cancel_event.wait(retry_delays[attempt]):
                raise IngestionCancelled("Ingesta cancelada durante la espera por bloqueo")
    raise FileLockedError(f"No se pudo abrir {path} tras {attempts} intentos") from last_error
