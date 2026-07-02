from __future__ import annotations

from knowledge_orchestrator.domain.broker_contracts import BrokerContractError
from knowledge_orchestrator.integrations.broker_client import (
    BrokerClient,
    PermanentBrokerError,
    TransientBrokerError,
)
from knowledge_orchestrator.repositories.workflow_repository import WorkflowRepository

from .broker_submission import attempt_broker_submission
from .workflow_planner import WorkflowPlanner


class BrokerDispatcher:
    def __init__(
        self,
        repository: WorkflowRepository,
        client: BrokerClient,
        *,
        backoff_seconds: tuple[float, ...] = (30.0, 60.0, 120.0),
    ) -> None:
        self.repository = repository
        self.client = client
        self.backoff_seconds = backoff_seconds

    async def dispatch_once(self) -> int:
        accepted = 0
        for candidate in self.repository.list_dispatchable():
            task = self.repository.claim_submission(candidate.task_id)
            if task is None:
                continue
            decision = await attempt_broker_submission(
                self.client,
                task.request_json,
                attempt=task.attempt,
                backoff_seconds=self.backoff_seconds,
            )
            if decision.kind == "retry":
                self.repository.release_submission(
                    task.task_id,
                    next_retry_at=decision.retry_at,
                    message=decision.message,
                )
            elif decision.kind == "exhausted":
                self.repository.mark_submission_error(task.task_id, "BROKER_UNAVAILABLE", decision.message or "")
            elif decision.kind == "permanent":
                self.repository.mark_submission_error(
                    task.task_id, "CONTRACT_VALIDATION_FAILED", decision.message or ""
                )
            else:
                self.repository.mark_accepted(task.task_id, decision.response or {})
                accepted += 1
        return accepted


class BrokerPoller:
    def __init__(
        self,
        repository: WorkflowRepository,
        client: BrokerClient,
        planner: WorkflowPlanner,
    ) -> None:
        self.repository = repository
        self.client = client
        self.planner = planner

    async def poll_once(self) -> int:
        updated = 0
        for task in self.repository.list_active_tasks():
            try:
                payload = await self.client.get_task(
                    task.broker_task_id or task.task_id,
                    status_url=task.status_url,
                )
            except TransientBrokerError:
                continue
            except (PermanentBrokerError, BrokerContractError) as error:
                self.repository.mark_submission_error(
                    task.task_id,
                    "CONTRACT_VALIDATION_FAILED",
                    str(error),
                )
                continue
            if self.repository.apply_status(task.task_id, payload):
                updated += 1
                self.planner.advance_workflow(task.workflow_id)
        return updated
