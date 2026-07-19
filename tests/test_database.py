from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from importlib.resources import files
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
                    {
                        "captures", "tasks", "events", "notes", "topics", "profiles", "schema_migrations",
                        "knowledge_claims", "evidence_links", "claim_embeddings", "update_candidates",
                        "note_revisions", "knowledge_claims_fts",
                    }
                    <= tables
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
                    8,
                )
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_migrates_existing_phase_one_database_without_losing_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Database(Path(temporary) / "orchestrator.db")
            with closing(database.connect()) as connection:
                connection.execute(
                    "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT)"
                )
                migration = files("knowledge_orchestrator").joinpath("migrations/001_initial.sql").read_text("utf-8")
                connection.executescript(migration)
                connection.execute("INSERT INTO schema_migrations VALUES (1, '2026-06-22T00:00:00Z')")
                connection.execute(
                    "INSERT INTO captures (capture_id, contract_version, source_type, title, status, "
                    "sha256, original_filename, metadata_json, transcript_content) "
                    "VALUES ('legacy_capture', '1.0', 'youtube', 'Legacy', 'PENDING', 'abc', "
                    "'legacy.md', '{\"plugin_version\":\"0.1.0\"}', 'texto')"
                )
                connection.commit()
            database.initialize()
            with closing(database.connect()) as connection:
                row = connection.execute(
                    "SELECT source_origin, topic_id FROM captures WHERE capture_id = 'legacy_capture'"
                ).fetchone()
                self.assertEqual(row["source_origin"], "PLUGIN_CAPTURE")
                self.assertIsNone(row["topic_id"])
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
                    8,
                )


if __name__ == "__main__":
    unittest.main()
