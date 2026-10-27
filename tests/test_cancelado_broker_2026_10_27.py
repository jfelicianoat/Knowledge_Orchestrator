"""Cancelar tareas desde el Broker dejaba los documentos en «Finalizados» como error y sin poder reprocesarlos."""

import unittest

from knowledge_orchestrator.ui.dashboard.trabajo import work_filter_key
from knowledge_orchestrator.ui.dashboard.trabajo_detalle import DetalleMixin
from knowledge_orchestrator.ui.snapshots import UiSnapshotService


def _row(capture_status: str, last_error_code: str | None, task_status: str) -> dict[str, object]:
    keys = ("progress_json", "task_error_code", "task_error_message", "last_error_message", "review_status",
            "archive_path", "source_path", "staging_path", "rejected_source_path", "started_at", "queued_at",
            "task_created_at", "model_used", "error_retryable", "attempt", "original_filename")
    row: dict[str, object] = dict.fromkeys(keys)
    row.update(capture_id="c1", task_id="t1", title="Doc", capture_status=capture_status, task_status=task_status,
               last_error_code=last_error_code, processing_path="I:/proc/doc.md",
               created_at="2026-10-27T17:00:00Z", updated_at="2026-10-27T17:00:00Z", original_filename="doc.md")
    return row


class CanceladoDesdeBrokerTests(unittest.TestCase):
    def test_broker_cancellation_goes_to_cancelled_tab_and_can_be_reprocessed(self) -> None:
        item = UiSnapshotService._work_item(_row("FAILED", "CANCELLED", "CANCELLED"))
        self.assertEqual(item.status, "CANCELLED")
        self.assertEqual(work_filter_key(item), "cancelled")
        self.assertTrue(DetalleMixin._can_send_item(item))

    def test_real_failure_still_needs_attention(self) -> None:
        item = UiSnapshotService._work_item(_row("FAILED", "TASK_TIMEOUT", "ERROR"))
        self.assertEqual(work_filter_key(item), "attention")


if __name__ == "__main__":
    unittest.main()
