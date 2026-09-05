from __future__ import annotations

import threading
import unittest

from knowledge_orchestrator.ui.startup import RuntimeStartup


class _SlowRuntime:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.stopped = threading.Event()

    def start(self) -> object:
        self.entered.set()
        if not self.release.wait(2):
            raise TimeoutError("la prueba no liberó el arranque")
        return object()

    def stop(self) -> None:
        self.stopped.set()


class RuntimeStartupTests(unittest.TestCase):
    def test_slow_recovery_does_not_block_the_ui_caller(self) -> None:
        runtime = _SlowRuntime()
        startup = RuntimeStartup(runtime)  # type: ignore[arg-type]

        startup.start()

        self.assertTrue(runtime.entered.wait(0.2))
        self.assertFalse(startup.done)
        runtime.release.set()
        self.assertTrue(startup.wait(0.5))
        self.assertIsNone(startup.error)

    def test_close_during_recovery_stops_runtime_as_soon_as_start_finishes(self) -> None:
        runtime = _SlowRuntime()
        startup = RuntimeStartup(runtime)  # type: ignore[arg-type]
        startup.start()
        self.assertTrue(runtime.entered.wait(0.2))

        startup.cancel()
        runtime.release.set()

        self.assertTrue(startup.wait(0.5))
        self.assertTrue(runtime.stopped.is_set())


if __name__ == "__main__":
    unittest.main()
