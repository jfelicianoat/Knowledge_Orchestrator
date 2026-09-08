from __future__ import annotations

import json
import logging
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.operations import (
    _read_log_tail,
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
            self.assertNotIn(b"abc123", archive.read("logs/orchestrator-tail.log"))
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

    def test_headers_quoted_assignments_and_query_values_hide_complete_credentials(self) -> None:
        examples = (
            "Authorization: Bearer fictitious-bearer\nHTTP 403",
            "Proxy-Authorization: Basic fictitious-basic\nHTTP 403",
            "Cookie: session=fictitious-cookie; other=also-private\nHTTP 403",
            'error {"access_token": "fictitious-json with spaces", "status": 403}',
            "error {'X-Admin-Token': 'fictitious-header with spaces', 'status': 403}",
            "https://fictitious-user@example.test/?api_key=fictitious-query&status=403",
            'password="fictitious-escaped\\\" still private" status=403',
        )
        for example in examples:
            with self.subTest(example=example):
                sanitized = sanitize(example)
                self.assertNotIn("fictitious", sanitized)
                self.assertNotIn("also-private", sanitized)
                self.assertNotIn("still private", sanitized)
                self.assertIn("403", sanitized)
        self.assertEqual(sanitize('password="unterminated private value'), "password=***REDACTED***")

    def test_nested_json_text_and_paths_are_sanitized_without_losing_operational_fields(self) -> None:
        payload = json.dumps({
            "message": json.dumps({"headers": {"Authorization": "Bearer fictitious-nested"}, "status": 503}),
            "request_id": "request-17",
        })
        sanitized = json.loads(sanitize(payload))
        self.assertEqual(sanitized["request_id"], "request-17")
        message = json.loads(sanitized["message"])
        self.assertEqual(message["status"], 503)
        self.assertEqual(message["headers"]["Authorization"], "***REDACTED***")
        self.assertNotIn("fictitious-path", sanitize(Path("logs") / "token=fictitious-path"))

    def test_runtime_logging_masks_configured_secret_in_messages_and_exception_traces(self) -> None:
        secret = "fictitious-runtime/credential+ñ"
        settings = replace(self.runtime.broker_worker.settings, admin_token=secret)
        build_runtime(self.runtime.paths, broker_settings=settings, enable_logging=True)
        logger = logging.getLogger("knowledge_orchestrator.test")
        logger.error("TASK_FAILED request-17 %s %s", secret, quote(secret, safe=""))
        try:
            raise ValueError(f"remote failure {secret}")
        except ValueError:
            logger.exception("BROKER_UNAVAILABLE")
        log_text = (self.runtime.paths.logs / "orchestrator.log").read_text("utf-8")
        self.assertNotIn(secret, log_text)
        self.assertNotIn(quote(secret, safe=""), log_text)
        records = [json.loads(line) for line in log_text.splitlines()]
        self.assertIn("TASK_FAILED request-17", records[-2]["message"])
        self.assertIn("ValueError", records[-1]["exception"])
        self.assertEqual(records[-1]["level"], "ERROR")

    def test_diagnostic_sanitizes_legacy_json_and_known_secret_without_rewriting_log(self) -> None:
        secret = "fictitious-current/credential+ñ"
        settings = replace(self.runtime.broker_worker.settings, admin_token=secret)
        records = [
            {"message": json.dumps({"token": "fictitious-previous", "status": 403}), "level": "ERROR"},
            {"message": f"remote failure {secret}", "request_id": "request-17"},
            {"message": "Authorization: Bearer fictitious-header\nHTTP 403"},
        ]
        original = "\n".join(json.dumps(record) for record in records) + "\n"
        log_path = self.runtime.paths.logs / "orchestrator.log"
        log_path.write_text(original, encoding="utf-8")
        result = export_diagnostics(self.runtime.database, self.runtime.paths, settings)
        with zipfile.ZipFile(result.path) as archive:
            for name in ("diagnostics.json", "logs/orchestrator-tail.log"):
                text = archive.read(name).decode("utf-8")
                self.assertNotIn("fictitious", text)
            exported = [json.loads(line) for line in archive.read("logs/orchestrator-tail.log").splitlines()]
        self.assertEqual(json.loads(exported[0]["message"])["status"], 403)
        self.assertEqual(exported[1]["request_id"], "request-17")
        self.assertEqual(log_path.read_text("utf-8"), original)

    def test_log_tail_drops_secret_fragments_and_unfinished_records(self) -> None:
        path = self.root / "tail.log"
        safe = b'{"message":"TASK_FAILED","status":503}\n'
        path.write_bytes(b'{"token":"' + b"private-fragment" * 50 + b'"}\n' + safe + b'{"token":"unfinished')
        self.assertEqual(_read_log_tail(path, max_bytes=150), safe.decode())
        path.write_bytes(b"private-fragment" * 50)
        self.assertEqual(_read_log_tail(path, max_bytes=100), "")

    def test_log_tail_keeps_complete_lines_at_exact_byte_boundary(self) -> None:
        path = self.root / "tail.log"
        safe = 'último evento\n'.encode()
        path.write_bytes(b"previous event\n" + safe)
        self.assertEqual(_read_log_tail(path, max_bytes=len(safe)), safe.decode())
        self.assertEqual(_read_log_tail(path, max_bytes=len(safe) - 1), "")
        self.assertEqual(_read_log_tail(self.root / "missing.log"), "")
        with self.assertRaises(ValueError):
            _read_log_tail(path, max_bytes=0)

    def test_excessive_nested_data_is_omitted_instead_of_failing_logging(self) -> None:
        nested = {"token": "fictitious-deep"}
        for _ in range(30):
            nested = {"nested": nested}
        sanitized = json.dumps(sanitize(nested))
        self.assertNotIn("fictitious", sanitized)
        self.assertIn("OMITTED", sanitized)
