from __future__ import annotations

import unittest

from knowledge_orchestrator.domain.contracts import parse_capture_bytes
from knowledge_orchestrator.domain.errors import CaptureContractError

from tests.helpers import valid_markdown


class CaptureContractTests(unittest.TestCase):
    def test_accepts_plugin_capture_v1(self) -> None:
        document = parse_capture_bytes(valid_markdown())
        self.assertEqual(document.capture_id, "yt_20260622_120000_dQw4w9WgXcQ")
        self.assertEqual(document.source_type, "youtube")
        self.assertTrue(document.transcript_content.startswith("[00:00:00]"))

    def test_rejects_missing_required_field(self) -> None:
        content = valid_markdown().replace(b'title: "V\xc3\xaddeo de prueba"\n', b"")
        with self.assertRaises(CaptureContractError) as raised:
            parse_capture_bytes(content)
        self.assertEqual(raised.exception.issue.field, "title")

    def test_rejects_duplicate_yaml_keys(self) -> None:
        content = valid_markdown().replace(
            b'contract_version: "1.0"\n',
            b'contract_version: "1.0"\ncontract_version: "1.0"\n',
        )
        with self.assertRaises(CaptureContractError) as raised:
            parse_capture_bytes(content)
        self.assertIn("duplicate key", raised.exception.issue.reason)

    def test_rejects_unsafe_yaml_tags(self) -> None:
        content = valid_markdown().replace(
            b'title: "V\xc3\xaddeo de prueba"',
            b"title: !!python/object/apply:os.system ['echo unsafe']",
        )
        with self.assertRaises(CaptureContractError):
            parse_capture_bytes(content)

    def test_accepts_capture_without_transcript_for_terminal_routing(self) -> None:
        document = parse_capture_bytes(valid_markdown(has_transcript=False))
        self.assertFalse(document.metadata["has_transcript"])
        self.assertEqual(document.transcript_content, "")

    def test_rejects_impossible_calendar_date(self) -> None:
        content = valid_markdown().replace(b'published_date: "2026-06-20"', b'published_date: "2026-02-31"')
        with self.assertRaises(CaptureContractError) as raised:
            parse_capture_bytes(content)
        self.assertEqual(raised.exception.issue.field, "published_date")


if __name__ == "__main__":
    unittest.main()
