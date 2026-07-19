from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from knowledge_orchestrator.domain.contracts import parse_capture_bytes
from knowledge_orchestrator.domain.models import CaptureRecord, CaptureStatus
from knowledge_orchestrator.services.recovery import RecoveryService
from tests.helpers import runtime, valid_markdown


class SimulatedCrash(RuntimeError):
    pass


class IngestionRecoveryTests(unittest.TestCase):
    def test_happy_path_creates_one_pending_row_and_processing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _database, repository, ingestion = runtime(Path(temporary))
            source = paths.inbox / "capture.md"
            source.write_bytes(valid_markdown())
            result = ingestion.ingest(source)

            self.assertTrue(result.accepted)
            self.assertEqual(repository.count(), 1)
            record = repository.get(result.capture_id or "")
            self.assertEqual(record.status, CaptureStatus.PENDING)
            self.assertTrue(record.processing_path.exists())
            self.assertFalse(source.exists())
            self.assertEqual(list(paths.staging.iterdir()), [])

    def test_invalid_contract_moves_to_failed_contracts_with_sidecar_and_no_row(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _database, repository, ingestion = runtime(Path(temporary))
            source = paths.inbox / "invalid.md"
            source.write_bytes(valid_markdown().replace(b"status: \"pending\"", b"status: \"wrong\""))
            result = ingestion.ingest(source)

            self.assertFalse(result.accepted)
            self.assertEqual(result.error_code, "CONTRACT_VALIDATION_FAILED")
            self.assertEqual(repository.count(), 0)
            rejected = paths.failed_contracts / "invalid.md"
            self.assertTrue(rejected.exists())
            payload = json.loads((paths.failed_contracts / "invalid.md.error.json").read_text("utf-8"))
            self.assertEqual(payload["field"], "status")
            self.assertEqual(payload["boundary"], "plugin_to_orchestrator")

    def test_quarantine_recovers_file_and_sidecar_after_each_crash_point(self) -> None:
        for crash_point in (
            "AFTER_QUARANTINE_INTENT",
            "AFTER_QUARANTINE_MOVE",
            "AFTER_QUARANTINE_SIDECAR",
        ):
            with self.subTest(crash_point=crash_point), tempfile.TemporaryDirectory() as temporary:
                def checkpoint(point: str, crash_point: str = crash_point) -> None:
                    if point == crash_point:
                        raise SimulatedCrash(point)

                paths, _database, repository, ingestion = runtime(Path(temporary), checkpoint=checkpoint)
                source = paths.inbox / "invalid.md"
                source.write_bytes(valid_markdown().replace(b"status: \"pending\"", b"status: \"wrong\""))
                with self.assertRaises(SimulatedCrash):
                    ingestion.ingest(source)

                report = RecoveryService(paths, repository).recover()
                self.assertEqual(report.quarantines_recovered, 1)
                self.assertFalse(source.exists())
                self.assertTrue((paths.failed_contracts / "invalid.md").exists())
                self.assertTrue((paths.failed_contracts / "invalid.md.error.json").exists())
                self.assertEqual(list(paths.failed.rglob(".quarantine-*.pending.json")), [])
                self.assertEqual(repository.count(), 0)

    def test_missing_transcript_is_terminal_and_never_creates_row(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _database, repository, ingestion = runtime(Path(temporary))
            source = paths.inbox / "without-transcript.md"
            source.write_bytes(valid_markdown(has_transcript=False))
            result = ingestion.ingest(source)
            self.assertEqual(result.error_code, "TRANSCRIPTION_MISSING")
            self.assertEqual(repository.count(), 0)
            self.assertTrue((paths.failed_transcriptions / source.name).exists())

    def test_every_protocol_crash_recovers_exactly_one_row_and_file(self) -> None:
        checkpoints = (
            "AFTER_STAGING_SYNC",
            "AFTER_STAGED_COMMIT",
            "AFTER_PROCESSING_MOVE",
            "AFTER_PENDING_COMMIT",
            "AFTER_SOURCE_REMOVAL",
        )
        for crash_point in checkpoints:
            with self.subTest(crash_point=crash_point), tempfile.TemporaryDirectory() as temporary:
                def checkpoint(point: str, crash_point: str = crash_point) -> None:
                    if point == crash_point:
                        raise SimulatedCrash(point)

                paths, _database, repository, ingestion = runtime(Path(temporary), checkpoint=checkpoint)
                source = paths.inbox / "capture.md"
                source.write_bytes(valid_markdown())
                with self.assertRaises(SimulatedCrash):
                    ingestion.ingest(source)

                RecoveryService(paths, repository).recover()
                self.assertEqual(repository.count(), 1)
                record = repository.get("yt_20260622_120000_dQw4w9WgXcQ")
                self.assertEqual(record.status, CaptureStatus.PENDING)
                self.assertEqual(len(list(paths.processing.glob("*.md"))), 1)
                self.assertEqual(len(list(paths.staging.glob("*.part"))), 0)
                self.assertFalse(source.exists())

    def test_duplicate_capture_is_quarantined_without_second_row(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _database, repository, ingestion = runtime(Path(temporary))
            source = paths.inbox / "capture.md"
            source.write_bytes(valid_markdown())
            self.assertTrue(ingestion.ingest(source).accepted)
            source.write_bytes(valid_markdown())
            duplicate = ingestion.ingest(source)
            self.assertEqual(duplicate.error_code, "DUPLICATE_CAPTURE")
            source.write_bytes(valid_markdown())
            third = ingestion.ingest(source)
            self.assertEqual(third.error_code, "DUPLICATE_CAPTURE")
            self.assertEqual(repository.count(), 1)
            self.assertEqual(len(list(paths.failed_duplicates.glob("*.md"))), 2)

    def test_keeps_original_if_it_changes_after_pending_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source_holder: dict[str, Path] = {}

            def checkpoint(point: str) -> None:
                if point == "AFTER_PENDING_COMMIT":
                    source_holder["path"].write_bytes(valid_markdown() + b"\nchanged")

            paths, _database, repository, ingestion = runtime(Path(temporary), checkpoint=checkpoint)
            source = paths.inbox / "capture.md"
            source_holder["path"] = source
            source.write_bytes(valid_markdown())
            with self.assertRaisesRegex(RuntimeError, "no se elimina"):
                ingestion.ingest(source)
            self.assertTrue(source.exists())
            self.assertEqual(repository.get("yt_20260622_120000_dQw4w9WgXcQ").status, CaptureStatus.PENDING)
            RecoveryService(paths, repository).recover()
            record = repository.get("yt_20260622_120000_dQw4w9WgXcQ")
            self.assertEqual(record.status, CaptureStatus.FAILED)
            self.assertTrue(source.exists())

    def test_locked_file_stays_in_inbox_without_database_row(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _database, repository, _ingestion = runtime(Path(temporary))
            source = paths.inbox / "capture.md"
            source.write_bytes(valid_markdown())

            def locked_reader(_path: Path) -> bytes:
                from knowledge_orchestrator.domain.errors import FileLockedError
                raise FileLockedError("locked")

            from knowledge_orchestrator.services.file_stability import FileStabilityChecker
            from knowledge_orchestrator.services.ingestion import IngestionService
            service = IngestionService(
                paths,
                repository,
                stability_checker=FileStabilityChecker(interval_seconds=0, sleep=lambda _seconds: None),
                read_file=locked_reader,
            )
            result = service.ingest(source)
            self.assertEqual(result.error_code, "FILE_LOCKED")
            self.assertTrue(source.exists())
            self.assertEqual(repository.count(), 0)

    def test_adopts_processing_orphan_without_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _database, repository, _ingestion = runtime(Path(temporary))
            orphan = paths.processing / "orphan.md"
            orphan.write_bytes(valid_markdown(capture_id="yt_orphan_001"))
            report = RecoveryService(paths, repository).recover()
            self.assertEqual(report.orphan_processing_recovered, 1)
            self.assertEqual(repository.count(), 1)
            self.assertEqual(repository.get("yt_orphan_001").status, CaptureStatus.PENDING)
            self.assertTrue(orphan.exists())

    def test_rebuilds_missing_staging_from_committed_inbox_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _database, repository, _ingestion = runtime(Path(temporary))
            source = paths.inbox / "capture.md"
            content = valid_markdown()
            source.write_bytes(content)
            document = parse_capture_bytes(content)
            repository.insert_staged(CaptureRecord(
                capture_id=document.capture_id,
                contract_version=document.contract_version,
                source_type=document.source_type,
                title=document.title,
                status=CaptureStatus.STAGED,
                source_path=source,
                staging_path=paths.staging / f"{document.capture_id}.part",
                processing_path=paths.processing / source.name,
                sha256=hashlib.sha256(content).hexdigest(),
                original_filename=source.name,
                metadata_json=json.dumps(dict(document.metadata), ensure_ascii=False),
                transcript_content=document.transcript_content,
            ))
            RecoveryService(paths, repository).recover()
            record = repository.get(document.capture_id)
            self.assertEqual(record.status, CaptureStatus.PENDING)
            self.assertTrue(record.processing_path.exists())
            self.assertFalse(source.exists())

    def test_marks_staged_row_failed_when_every_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths, _database, repository, _ingestion = runtime(Path(temporary))
            content = valid_markdown(capture_id="yt_missing_001")
            document = parse_capture_bytes(content)
            repository.insert_staged(CaptureRecord(
                capture_id=document.capture_id,
                contract_version=document.contract_version,
                source_type=document.source_type,
                title=document.title,
                status=CaptureStatus.STAGED,
                source_path=paths.inbox / "missing.md",
                staging_path=paths.staging / "missing.part",
                processing_path=paths.processing / "missing.md",
                sha256=hashlib.sha256(content).hexdigest(),
                original_filename="missing.md",
                metadata_json=json.dumps(dict(document.metadata), ensure_ascii=False),
                transcript_content=document.transcript_content,
            ))
            report = RecoveryService(paths, repository).recover()
            record = repository.get(document.capture_id)
            self.assertEqual(report.failed, 1)
            self.assertEqual(record.status, CaptureStatus.FAILED)
            self.assertEqual(record.last_error_code, "STAGING_RECOVERY_FAILED")


if __name__ == "__main__":
    unittest.main()
