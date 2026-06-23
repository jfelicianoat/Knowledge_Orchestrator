from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.domain.broker_contracts import validate_create_task_request
from knowledge_orchestrator.domain.broker_models import StepKind, TaskStatus
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.broker_dispatch import BrokerDispatcher
from knowledge_orchestrator.services.file_stability import FileStabilityChecker
from knowledge_orchestrator.services.workflow_planner import WorkflowPlanner
from tests.helpers import generic_markdown


class FakeAcceptingBroker:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.active_calls = 0
        self.maximum_parallel_calls = 0

    async def create_task(self, payload: dict) -> dict:
        self.active_calls += 1
        self.maximum_parallel_calls = max(self.maximum_parallel_calls, self.active_calls)
        self.calls.append(payload["task_id"])
        self.active_calls -= 1
        return {
            "task_id": payload["task_id"],
            "status": "queued",
            "status_url": f"/api/v1/tasks/{payload['task_id']}",
            "cancel_url": f"/api/v1/tasks/{payload['task_id']}",
        }


class PhaseThreeWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def make_runtime(self, root: Path, *, capture_id: str, transcript: str):
        runtime = build_runtime(PipelinePaths.under(root))
        runtime.ingestion.stability_checker = FileStabilityChecker(interval_seconds=0, sleep=lambda _: None)
        source = runtime.paths.inbox / f"{capture_id}.md"
        document = generic_markdown(capture_id=capture_id).decode("utf-8")
        document = document.replace("Contenido aportado manualmente por el usuario.", transcript)
        source.write_text(document, encoding="utf-8")
        result = runtime.ingestion.ingest(source)
        self.assertTrue(result.accepted)
        return runtime

    async def test_single_task_is_rendered_persisted_and_completed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = self.make_runtime(Path(temporary), capture_id="document_single", transcript="Texto breve.")
            workflow_id = runtime.workflow_planner.plan_capture("document_single")
            tasks = runtime.workflow_repository.list_workflow_tasks(workflow_id)
            self.assertEqual(len(tasks), 1)
            self.assertIs(tasks[0].step_kind, StepKind.SINGLE)
            validate_create_task_request(json.loads(tasks[0].request_json))

            runtime.workflow_repository.apply_status(tasks[0].task_id, {
                "task_id": tasks[0].task_id,
                "status": "success",
                "result": {"assistant_content": "Nota final"},
                "error": None,
            })
            runtime.workflow_planner.advance_workflow(workflow_id)
            workflow = runtime.workflow_repository.get_workflow(workflow_id)
            self.assertEqual(workflow.final_result, "Nota final")
            self.assertEqual(workflow.status.value, "SUCCESS")

    async def test_chunk_tasks_are_all_submitted_without_waiting_for_first_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = self.make_runtime(Path(temporary), capture_id="document_chunks", transcript=("dato técnico " * 5000))
            planner = WorkflowPlanner(
                runtime.repository,
                runtime.domain_repository,
                runtime.workflow_repository,
                max_context_tokens=6000,
                safety_tokens=100,
            )
            workflow_id = planner.plan_capture("document_chunks")
            tasks = runtime.workflow_repository.list_workflow_tasks(workflow_id)
            self.assertGreater(len(tasks), 1)
            self.assertTrue(all(task.step_kind is StepKind.CHUNK for task in tasks))

            broker = FakeAcceptingBroker()
            accepted = await BrokerDispatcher(runtime.workflow_repository, broker).dispatch_once()
            queued = runtime.workflow_repository.list_workflow_tasks(workflow_id)
            self.assertEqual(accepted, len(tasks))
            self.assertTrue(all(task.status is TaskStatus.QUEUED for task in queued))
            self.assertEqual(broker.maximum_parallel_calls, 1)

    async def test_synthesis_is_created_only_after_all_chunks_succeed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = self.make_runtime(Path(temporary), capture_id="document_synthesis", transcript=("hecho " * 6000))
            planner = WorkflowPlanner(
                runtime.repository,
                runtime.domain_repository,
                runtime.workflow_repository,
                max_context_tokens=6000,
                safety_tokens=100,
            )
            workflow_id = planner.plan_capture("document_synthesis")
            chunks = runtime.workflow_repository.list_workflow_tasks(workflow_id)
            for index, task in enumerate(chunks):
                runtime.workflow_repository.apply_status(task.task_id, {
                    "task_id": task.task_id,
                    "status": "success",
                    "result": {"assistant_content": f"Parcial {index}"},
                    "error": None,
                })
                planner.advance_workflow(workflow_id)
            tasks = runtime.workflow_repository.list_workflow_tasks(workflow_id)
            synthesis = [task for task in tasks if task.step_kind is StepKind.SYNTHESIS]
            self.assertEqual(len(synthesis), 1)
            self.assertIn("Parcial 0", synthesis[0].input_text)
            validate_create_task_request(json.loads(synthesis[0].request_json))

    async def test_restart_reopens_interrupted_submission_with_same_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = self.make_runtime(Path(temporary), capture_id="document_restart", transcript="Texto breve.")
            workflow_id = runtime.workflow_planner.plan_capture("document_restart")
            original = runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
            claimed = runtime.workflow_repository.claim_submission(original.task_id)
            self.assertEqual(claimed.status.value, "SUBMITTING")

            self.assertEqual(runtime.workflow_repository.recover_interrupted_submissions(), 1)
            recovered = runtime.workflow_repository.get_task(original.task_id)
            self.assertEqual(recovered.status, TaskStatus.READY)
            self.assertEqual(recovered.idempotency_key, original.idempotency_key)


if __name__ == "__main__":
    unittest.main()
