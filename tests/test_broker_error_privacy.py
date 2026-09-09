from __future__ import annotations

import json
import tempfile
import traceback
import unittest
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

import httpx

from knowledge_orchestrator.config import BrokerSettings
from knowledge_orchestrator.integrations.broker_client import (
    BrokerClient,
    PermanentBrokerError,
    TransientBrokerError,
)
from knowledge_orchestrator.services.broker_dispatch import BrokerDispatcher
from tests import test_phase_six_semantic_maintenance as phase_six
from tests import test_phase_three_workflows as phase_three


class BrokerErrorPrivacyTests(unittest.IsolatedAsyncioTestCase):
    make_runtime = phase_three.PhaseThreeWorkflowTests.make_runtime
    credential = "fictitious-private/+123"

    def client(self, handler):
        return BrokerClient(
            BrokerSettings(base_url="http://broker.test", admin_token=self.credential),
            transport=httpx.MockTransport(handler),
        )

    async def test_http_errors_hide_credentials_preserving_classification_and_codes(self):
        for status in (400, 401, 403, 422, 429, 502, 503, 504):
            for wrapper in ("detail", "error", None):
                with self.subTest(status=status, wrapper=wrapper):
                    detail = {
                        "code": "ADMIN_AUTH_REQUIRED",
                        "message": f"busy {self.credential} {quote(self.credential, safe='')}",
                    }
                    body = {wrapper: detail} if wrapper else detail
                    client = self.client(lambda request, status=status, body=body: httpx.Response(status, json=body))
                    expected = (
                        TransientBrokerError if status in (401, 403, 429, 502, 503, 504) else PermanentBrokerError
                    )
                    try:
                        with self.assertRaises(expected) as caught:
                            await client.health()
                        self.assertNotIn(self.credential, str(caught.exception))
                        self.assertNotIn(quote(self.credential, safe=""), str(caught.exception))
                        self.assertIn("busy", str(caught.exception))
                        self.assertEqual(caught.exception.status_code, status)
                        self.assertEqual(caught.exception.code, "ADMIN_AUTH_REQUIRED")
                    finally:
                        await client.close()

    async def test_network_exception_trace_does_not_restore_original_secret(self):
        def handler(request):
            raise httpx.ConnectError(f"unreachable {self.credential}", request=request)

        client = self.client(handler)
        try:
            try:
                await client.health()
            except TransientBrokerError as error:
                self.assertIn("unreachable", str(error))
                self.assertNotIn(self.credential, traceback.format_exc())
            else:
                self.fail("Expected recoverable network error")
        finally:
            await client.close()

    async def test_late_response_after_rotation_hides_old_and_current_credentials(self):
        replacement = "fictitious-replacement-456"
        seen = []

        async def handler(request):
            seen.append(request.headers["X-Admin-Token"])
            if len(seen) == 1:
                await client.reconfigure(BrokerSettings(base_url="http://broker.test", admin_token=replacement))
                return httpx.Response(403, json={"detail": {
                    "code": f"rejected {self.credential} {replacement}",
                    "message": f"credential rejected: {self.credential} {replacement}",
                }})
            return httpx.Response(200, json={"authenticated": True, "auth_required": True})

        client = self.client(handler)
        try:
            with self.assertRaises(TransientBrokerError) as caught:
                await client.auth_check()
            for secret in (self.credential, replacement):
                self.assertNotIn(secret, str(caught.exception))
                self.assertNotIn(secret, caught.exception.code)
            self.assertTrue((await client.auth_check())["authenticated"])
            self.assertEqual(seen, [self.credential, replacement])
        finally:
            await client.close()

    async def test_failed_task_error_is_redacted_before_workflow_and_semantic_storage(self):
        payload = {
            "task_id": "broker_task_1", "status": "failed",
            "created_at": "2026-09-08T10:00:00Z", "updated_at": "2026-09-08T10:01:00Z",
            "execution_strategy": "single", "execution_preset": "fast", "selection_mode": "auto",
            "progress": {"phase": "failed"}, "result": None,
            "error": {"code": "MODEL_UNAVAILABLE", "message": f"busy {self.credential}", "retryable": True},
        }
        client = self.client(lambda request: httpx.Response(200, json=payload))
        try:
            status = await client.get_task("broker_task_1")
        finally:
            await client.close()
        self.assertTrue(status["error"]["retryable"])
        with tempfile.TemporaryDirectory() as temporary:
            runtime = self.make_runtime(Path(temporary), capture_id="privacy", transcript="Texto breve.")
            workflow_id = runtime.workflow_planner.plan_capture("privacy")
            task = runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
            runtime.workflow_repository.apply_status(task.task_id, status)
            repository = runtime.semantic_repository
            self.runtime = runtime
            note = phase_six.PhaseSixSemanticMaintenanceTests.publish(self, "privacy_note", "# Nota\n\nDato.")
            job_id = f"semantic_extract_note_{note.note_id}"
            repository.claim_job(job_id)
            repository.accept_job(job_id, {"task_id": "broker_task_1", "status_url": "/api/v1/tasks/broker_task_1"})
            repository.update_job_status(job_id, status)
            with closing(runtime.database.connect(readonly=True)) as connection:
                task_row = dict(connection.execute(
                    "SELECT status,error_code,error_message,response_json FROM tasks WHERE task_id=?", (task.task_id,)
                ).fetchone())
                job_row = dict(connection.execute(
                    "SELECT status,error_code,error_message FROM semantic_jobs WHERE job_id=?", (job_id,)
                ).fetchone())
                events = [dict(row) for row in connection.execute("SELECT * FROM events")]
            for row in (task_row, job_row):
                self.assertEqual(row["status"], "ERROR")
                self.assertEqual(row["error_code"], "MODEL_UNAVAILABLE")
                self.assertIn("busy", row["error_message"])
            self.assertNotIn(self.credential, json.dumps([task_row, job_row, events]))
        self.assertIn(self.credential, payload["error"]["message"])

    async def test_submission_persists_retry_without_credential(self):
        client = self.client(lambda request: httpx.Response(503, json={"message": f"busy {self.credential}"}))
        try:
            with tempfile.TemporaryDirectory() as temporary:
                runtime = self.make_runtime(Path(temporary), capture_id="retry_privacy", transcript="Texto breve.")
                workflow_id = runtime.workflow_planner.plan_capture("retry_privacy")
                task = runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
                dispatcher = BrokerDispatcher(runtime.workflow_repository, client)
                self.assertEqual(await dispatcher.dispatch_once({task.task_id}), 0)
                saved = runtime.workflow_repository.get_task(task.task_id)
                self.assertEqual(saved.status.value, "READY")
                self.assertIsNotNone(saved.next_retry_at)
                self.assertNotIn(self.credential, saved.error_message)
                self.assertIn("busy", saved.error_message)
        finally:
            await client.close()
