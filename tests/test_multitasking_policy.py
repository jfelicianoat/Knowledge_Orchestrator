from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.domain.broker_models import StepKind, TaskStatus, WorkflowStatus
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.file_stability import FileStabilityChecker
from knowledge_orchestrator.services.workflow_planner import WorkflowPlanner
from tests.helpers import generic_markdown


class MultitaskingPolicyTests(unittest.TestCase):
    def make_runtime(self, root: Path, capture_id: str, transcript: str):
        runtime = build_runtime(PipelinePaths.under(root))
        runtime.ingestion.stability_checker = FileStabilityChecker(interval_seconds=0, sleep=lambda _: None)
        profile = runtime.profiles.list_profiles(enabled_only=True)[0]
        runtime.profiles.save_profile(replace(
            profile,
            execution_strategy="mixture_of_agents",
            multitasking_steps=("single", "synthesis"),
            consensus_preset="fast",
            consensus_max_proposers=3,
            consensus_fallback_to_single=True,
        ))
        source = runtime.paths.inbox / f"{capture_id}.md"
        document = generic_markdown(capture_id=capture_id).decode("utf-8")
        document = document.replace("Contenido aportado manualmente por el usuario.", transcript)
        source.write_text(document, encoding="utf-8")
        self.assertTrue(runtime.ingestion.ingest(source).accepted)
        return runtime

    def test_single_step_can_request_fast_consensus_by_explicit_profile_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = self.make_runtime(Path(temporary), "document_consensus_single", "Texto breve.")
            workflow_id = runtime.workflow_planner.plan_capture("document_consensus_single")
            task = runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
            request = json.loads(task.request_json)
            self.assertEqual(request["execution"]["strategy"], "mixture_of_agents")
            self.assertEqual(request["execution"]["preset"], "fast")
            self.assertEqual(request["execution"]["max_proposers"], 3)
            self.assertTrue(task.strategy_fallback_allowed)

    def test_chunks_remain_single_and_only_synthesis_uses_consensus(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = self.make_runtime(Path(temporary), "document_consensus_chunks", "hecho " * 6000)
            profile = runtime.profiles.list_profiles(enabled_only=True)[0]
            runtime.profiles.save_profile(replace(
                profile,
                multitasking_steps=("synthesis",),
            ))
            planner = WorkflowPlanner(
                runtime.repository, runtime.domain_repository, runtime.workflow_repository,
                max_context_tokens=6000, safety_tokens=100,
            )
            workflow_id = planner.plan_capture("document_consensus_chunks")
            chunks = runtime.workflow_repository.list_workflow_tasks(workflow_id)
            self.assertGreater(len(chunks), 1)
            self.assertTrue(all(json.loads(task.request_json)["execution"]["strategy"] == "single" for task in chunks))
            for index, task in enumerate(chunks):
                runtime.workflow_repository.apply_status(task.task_id, {
                    "task_id": task.task_id, "status": "success",
                    "result": {"assistant_content": f"Parcial {index}"}, "error": None,
                })
            planner.advance_workflow(workflow_id)
            synthesis = next(
                task for task in runtime.workflow_repository.list_workflow_tasks(workflow_id)
                if task.step_kind is StepKind.SYNTHESIS
            )
            self.assertEqual(json.loads(synthesis.request_json)["execution"]["strategy"], "mixture_of_agents")

    def test_consensus_failure_creates_one_idempotent_single_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = self.make_runtime(Path(temporary), "document_consensus_fallback", "Texto breve.")
            workflow_id = runtime.workflow_planner.plan_capture("document_consensus_fallback")
            original = runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
            runtime.workflow_repository.claim_submission(original.task_id)
            runtime.workflow_repository.mark_accepted(original.task_id, {
                "task_id": "broker_consensus_failure", "status": "queued",
                "execution_strategy": "mixture_of_agents", "execution_preset": "fast",
                "selection_mode": "auto", "status_url": "/api/v1/tasks/broker_consensus_failure",
                "cancel_url": "/api/v1/tasks/broker_consensus_failure",
            })
            runtime.workflow_repository.apply_status(original.task_id, {
                "task_id": "broker_consensus_failure", "status": "failed",
                "created_at": "2026-06-23T10:00:00Z", "updated_at": "2026-06-23T10:01:00Z",
                "progress": {"phase": "failed"}, "result": None,
                "error": {"code": "CONSENSUS_QUORUM_NOT_REACHED", "message": "Sin quorum", "retryable": False},
            })
            runtime.workflow_planner.advance_workflow(workflow_id)
            runtime.workflow_planner.advance_workflow(workflow_id)
            tasks = runtime.workflow_repository.list_workflow_tasks(workflow_id)
            fallback = [task for task in tasks if task.replacement_for_task_id == original.task_id]
            self.assertEqual(len(fallback), 1)
            self.assertEqual(json.loads(fallback[0].request_json)["execution"]["strategy"], "single")
            self.assertEqual(fallback[0].status, TaskStatus.READY)
            self.assertNotEqual(runtime.workflow_repository.get_workflow(workflow_id).status, WorkflowStatus.ERROR)

    def test_startup_recovers_consensus_failure_and_creates_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = Path(temporary)
            runtime = self.make_runtime(paths, "document_consensus_recovery", "Texto breve.")
            workflow_id = runtime.workflow_planner.plan_capture("document_consensus_recovery")
            original = runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
            runtime.workflow_repository.claim_submission(original.task_id)
            runtime.workflow_repository.mark_accepted(original.task_id, {
                "task_id": "broker_recovery", "status": "queued", "execution_strategy": "mixture_of_agents",
                "execution_preset": "fast", "selection_mode": "auto",
                "status_url": "/api/v1/tasks/broker_recovery", "cancel_url": "/api/v1/tasks/broker_recovery",
            })
            runtime.workflow_repository.apply_status(original.task_id, {
                "task_id": "broker_recovery", "status": "failed",
                "created_at": "2026-06-23T10:00:00Z", "updated_at": "2026-06-23T10:01:00Z",
                "progress": {"phase": "failed"}, "result": None,
                "error": {"code": "CONSENSUS_QUORUM_NOT_REACHED", "message": "Sin quorum"},
            })

            restarted = build_runtime(PipelinePaths.under(paths))
            restarted.recover_once(ingest_inbox=False)
            tasks = restarted.workflow_repository.list_workflow_tasks(workflow_id)
            self.assertEqual(len([task for task in tasks if task.replacement_for_task_id == original.task_id]), 1)

    def test_budget_failure_never_degrades_silently_to_single(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = self.make_runtime(Path(temporary), "document_consensus_budget", "Texto breve.")
            workflow_id = runtime.workflow_planner.plan_capture("document_consensus_budget")
            original = runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
            runtime.workflow_repository.claim_submission(original.task_id)
            runtime.workflow_repository.mark_accepted(original.task_id, {
                "task_id": "broker_budget", "status": "queued", "execution_strategy": "mixture_of_agents",
                "execution_preset": "fast", "selection_mode": "auto",
                "status_url": "/api/v1/tasks/broker_budget", "cancel_url": "/api/v1/tasks/broker_budget",
            })
            runtime.workflow_repository.apply_status(original.task_id, {
                "task_id": "broker_budget", "status": "failed",
                "created_at": "2026-06-23T10:00:00Z", "updated_at": "2026-06-23T10:01:00Z",
                "progress": {"phase": "failed"}, "result": None,
                "error": {"code": "BUDGET_EXCEEDED", "message": "Presupuesto agotado"},
            })
            runtime.workflow_planner.advance_workflow(workflow_id)
            self.assertEqual(runtime.workflow_repository.get_workflow(workflow_id).status, WorkflowStatus.ERROR)
            self.assertEqual(len(runtime.workflow_repository.list_workflow_tasks(workflow_id)), 1)


if __name__ == "__main__":
    unittest.main()
