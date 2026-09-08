from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from tests import test_phase_three_workflows as phase_three


class WorkflowAuditPrivacyTests(unittest.TestCase):
    make_runtime = phase_three.PhaseThreeWorkflowTests.make_runtime

    def prepare(self, root: Path):
        runtime = self.make_runtime(root, capture_id="audit_privacy", transcript="Texto breve.")
        workflow_id = runtime.workflow_planner.plan_capture("audit_privacy")
        task = runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
        return runtime, workflow_id, task

    @staticmethod
    def events(runtime):
        with closing(runtime.database.connect(readonly=True)) as connection:
            return [dict(row) for row in connection.execute(
                "SELECT event_type,message,details_json FROM events WHERE event_type IN "
                "('BROKER_RESULT_WARNING','BROKER_CITATION_WARNING','CONSENSUS_FALLBACK_REQUIRED')"
            )]

    def test_warning_events_keep_counts_and_task_link_without_copying_remote_text_or_urls(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime, workflow_id, task = self.prepare(Path(temporary))
            private = "PRIVATE_REMOTE_CONTENT Authorization: Bearer fictitious-only"
            result = {
                "assistant_content": "Resultado",
                "warnings": [private, "Otra reserva privada"],
                "agent": {"citations": {"unsupported": ["https://example.test/?token=fictitious-url"]}},
            }
            payload = {"status": "completed", "result": result, "error": None}
            self.assertTrue(runtime.workflow_repository.apply_status(task.task_id, payload))
            self.assertFalse(runtime.workflow_repository.apply_status(task.task_id, payload))
            events = self.events(runtime)
            self.assertEqual(len(events), 2)
            serialized = json.dumps(events)
            for fragment in ("PRIVATE_REMOTE_CONTENT", "fictitious", "Otra reserva", "https://"):
                self.assertNotIn(fragment, serialized)
            by_type = {event["event_type"]: json.loads(event["details_json"]) for event in events}
            self.assertEqual(by_type["BROKER_RESULT_WARNING"], {"task_id": task.task_id, "warning_count": 2})
            self.assertEqual(by_type["BROKER_CITATION_WARNING"], {"task_id": task.task_id, "unsupported_count": 1})
            with closing(runtime.database.connect(readonly=True)) as connection:
                row = connection.execute(
                    "SELECT response_json,broker_metadata_json FROM tasks WHERE task_id=?", (task.task_id,)
                ).fetchone()
                completed = connection.execute(
                    "SELECT completed_steps FROM workflows WHERE workflow_id=?", (workflow_id,)
                ).fetchone()[0]
            self.assertEqual(json.loads(row["response_json"]), payload)
            self.assertEqual(json.loads(row["broker_metadata_json"])["warnings"], result["warnings"])
            self.assertEqual(completed, 1)

    def test_fallback_event_keeps_allowlisted_code_and_does_not_change_fallback_decision(self):
        for allowed in (True, False):
            with self.subTest(allowed=allowed), tempfile.TemporaryDirectory() as temporary:
                runtime, workflow_id, task = self.prepare(Path(temporary))
                with runtime.database.transaction() as connection:
                    connection.execute(
                        "UPDATE tasks SET execution_strategy='mixture_of_agents',strategy_fallback_allowed=? "
                        "WHERE task_id=?", (int(allowed), task.task_id),
                    )
                payload = {"status": "failed", "error": {
                    "code": "CONSENSUS_QUORUM_NOT_REACHED", "message": "PRIVATE_REMOTE_CONTENT",
                    "retryable": False,
                }}
                self.assertTrue(runtime.workflow_repository.apply_status(task.task_id, payload))
                self.assertFalse(runtime.workflow_repository.apply_status(task.task_id, payload))
                events = self.events(runtime)
                self.assertEqual(len(events), int(allowed))
                self.assertNotIn("PRIVATE_REMOTE_CONTENT", json.dumps(events))
                if allowed:
                    self.assertEqual(json.loads(events[0]["details_json"]), {
                        "task_id": task.task_id, "error_code": "CONSENSUS_QUORUM_NOT_REACHED",
                    })
                workflow = runtime.workflow_repository.get_workflow(workflow_id)
                self.assertEqual(workflow.status.value == "ERROR", not allowed)
                self.assertEqual(runtime.workflow_repository.get_task(task.task_id).error_message,
                                 "PRIVATE_REMOTE_CONTENT")

    def test_audit_write_failure_rolls_back_task_and_completion_counter(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime, workflow_id, task = self.prepare(Path(temporary))
            payload = {"status": "completed", "result": {"assistant_content": "Resultado", "warnings": ["Aviso"]}}
            with runtime.database.transaction() as connection:
                connection.execute(
                    "CREATE TRIGGER fail_warning_audit BEFORE INSERT ON events "
                    "WHEN NEW.event_type='BROKER_RESULT_WARNING' BEGIN SELECT RAISE(ABORT,'test'); END"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                runtime.workflow_repository.apply_status(task.task_id, payload)
            self.assertEqual(runtime.workflow_repository.get_task(task.task_id).status, task.status)
            self.assertEqual(self.events(runtime), [])
            with closing(runtime.database.connect(readonly=True)) as connection:
                self.assertEqual(connection.execute(
                    "SELECT completed_steps FROM workflows WHERE workflow_id=?", (workflow_id,)
                ).fetchone()[0], 0)
            with runtime.database.transaction() as connection:
                connection.execute("DROP TRIGGER fail_warning_audit")
            self.assertTrue(runtime.workflow_repository.apply_status(task.task_id, payload))
            self.assertEqual(len(self.events(runtime)), 1)
