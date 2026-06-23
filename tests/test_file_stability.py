from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from knowledge_orchestrator.services.file_stability import (
    FileStabilityChecker,
    read_bytes_with_lock_retries,
)


class FileStabilityTests(unittest.TestCase):
    def test_requires_three_consecutive_equal_size_and_mtime_observations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "capture.md"
            path.write_text("a", encoding="utf-8")
            sleeps: list[float] = []

            def mutate_once(seconds: float) -> None:
                sleeps.append(seconds)
                if len(sleeps) == 1:
                    path.write_text("contenido más largo", encoding="utf-8")

            checker = FileStabilityChecker(interval_seconds=1, sleep=mutate_once, max_observations=6)
            size, _mtime = checker.wait_until_stable(path)
            self.assertEqual(size, len("contenido más largo".encode("utf-8")))
            self.assertEqual(sleeps, [1, 1, 1])

    def test_retries_locked_file_with_backoff_1_2_4(self) -> None:
        attempts = 0
        sleeps: list[float] = []

        def opener(_path: Path, _mode: str):
            nonlocal attempts
            attempts += 1
            if attempts <= 3:
                raise PermissionError("locked")
            return io.BytesIO(b"ok")

        result = read_bytes_with_lock_retries(
            Path("capture.md"), opener=opener, sleep=sleeps.append
        )
        self.assertEqual(result, b"ok")
        self.assertEqual(attempts, 4)
        self.assertEqual(sleeps, [1.0, 2.0, 4.0])


if __name__ == "__main__":
    unittest.main()
