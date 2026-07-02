from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from knowledge_orchestrator.services.filesystem import (
    atomic_write_json,
    unique_destination,
    write_synced,
)


class FilesystemPrimitivesTests(unittest.TestCase):
    def test_write_synced_creates_parent_directories_and_writes_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "capture.md"

            write_synced(path, b"contenido")

            self.assertEqual(path.read_bytes(), b"contenido")

    def test_write_synced_overwrites_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "capture.md"
            write_synced(path, b"primero")

            write_synced(path, b"segundo")

            self.assertEqual(path.read_bytes(), b"segundo")

    def test_atomic_write_json_persists_payload_and_leaves_no_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state" / "profile.json"
            payload = {"b": 2, "a": 1}

            atomic_write_json(path, payload)

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), payload)
            leftovers = [item for item in path.parent.iterdir() if item != path]
            self.assertEqual(leftovers, [])

    def test_atomic_write_json_replaces_previous_content_without_partial_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            atomic_write_json(path, {"version": 1})

            atomic_write_json(path, {"version": 2})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"version": 2})
            leftovers = [item for item in path.parent.iterdir() if item != path]
            self.assertEqual(leftovers, [])

    def test_unique_destination_returns_candidate_when_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)

            destination = unique_destination(directory, "note.md")

            self.assertEqual(destination, directory / "note.md")

    def test_unique_destination_disambiguates_with_discriminator_then_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "note.md").write_text("existing", encoding="utf-8")

            first = unique_destination(directory, "note.md", discriminator="dup")
            self.assertEqual(first, directory / "note [dup].md")
            first.write_text("also existing", encoding="utf-8")

            second = unique_destination(directory, "note.md", discriminator="dup")
            self.assertEqual(second, directory / "note [dup-2].md")


if __name__ == "__main__":
    unittest.main()
