from __future__ import annotations

import json
import logging
import tempfile
import unittest
import zipfile
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.operations import (
    backup_database,
    configure_logging,
    export_diagnostics,
    sanitize,
    shutdown_logging,
)


class PhaseEightOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runtime = build_runtime(PipelinePaths.under(self.root))

    def tearDown(self) -> None:
        shutdown_logging()
        self.temporary.cleanup()

    def test_logging_is_json_rotating_and_written_under_data_root(self) -> None:
        log_path = configure_logging(self.runtime.paths)
        logging.getLogger("knowledge_orchestrator.test").info("operational event")

        content = log_path.read_text(encoding="utf-8").strip().splitlines()

        self.assertTrue(content)
        payload = json.loads(content[-1])
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["message"], "operational event")
        self.assertEqual(log_path.parent, self.runtime.paths.logs)

    def test_backup_uses_sqlite_backup_api_and_keeps_database_readable(self) -> None:
        result = backup_database(self.runtime.database, self.runtime.paths)

        self.assertTrue(result.path.exists())
        self.assertEqual(result.path.parent, self.runtime.paths.backups)
        self.assertGreater(result.size_bytes, 0)

    def test_diagnostics_zip_excludes_database_and_redacts_secret_like_values(self) -> None:
        configure_logging(self.runtime.paths)
        logging.getLogger("knowledge_orchestrator.test").warning("token=abc123 should be sanitized by key metadata")
        target = self.runtime.paths.diagnostics / "diagnostics.zip"

        result = export_diagnostics(
            self.runtime.database,
            self.runtime.paths,
            self.runtime.broker_worker.settings,
            output_path=target,
        )

        self.assertTrue(result.path.exists())
        with zipfile.ZipFile(result.path) as archive:
            names = set(archive.namelist())
            manifest = json.loads(archive.read("diagnostics.json").decode("utf-8"))
        self.assertIn("diagnostics.json", names)
        self.assertIn("logs/orchestrator-tail.log", names)
        self.assertNotIn("orchestrator.db", names)
        self.assertIn("database", manifest)
        self.assertIn("directories", manifest)

    def test_sanitize_redacts_sensitive_keys_and_url_credentials(self) -> None:
        payload = {
            "api_key": "secret",
            "nested": {"password": "secret"},
            "url": "https://user:pass@example.test/path",
            "line": "token=abc123",
            "safe": "value",
        }

        sanitized = sanitize(payload)

        self.assertEqual(sanitized["api_key"], "***REDACTED***")
        self.assertEqual(sanitized["nested"]["password"], "***REDACTED***")
        self.assertEqual(sanitized["url"], "https://***:***@example.test/path")
        self.assertEqual(sanitized["line"], "token=***REDACTED***")
        self.assertEqual(sanitized["safe"], "value")
