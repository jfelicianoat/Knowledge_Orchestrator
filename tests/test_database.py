from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from knowledge_orchestrator.repositories.database import Database


class DatabaseTests(unittest.TestCase):
    def test_initializes_wal_and_all_phase_one_tables_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "state" / "orchestrator.db")
            database.initialize()
            database.initialize()
            self.assertEqual(database.journal_mode(), "wal")
            with closing(database.connect()) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                self.assertTrue(
                    {"captures", "tasks", "events", "notes", "topics", "profiles", "schema_migrations"}
                    <= tables
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
                    1,
                )
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
