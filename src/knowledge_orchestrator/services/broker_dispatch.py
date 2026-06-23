from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from knowledge_orchestrator.domain.broker_contracts import BrokerContractError
from knowledge_orchestrator.integrations.broker_client import (
    BrokerClient,
    PermanentBrokerError,
    TransientBrokerError,
)
from knowledge_orchestrator.repositories.workflow_repository import WorkflowRepository

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
            try:
                response = await self.client.create_task(json.loads(task.request_json))
            except TransientBrokerError as error:
                retry_index = task.attempt - 1
                if retry_index < len(self.backoff_seconds):
                    retry_at = datetime.now(timezone.utc) + timedelta(seconds=self.backoff_seconds[retry_index])
                    self.repository.release_submission(
                        task.task_id,
                        next_retry_at=retry_at.isoformat(),
                        message=str(error),
                    )
                else:
                    self.repository.mark_submission_error(task.task_id, "BROKER_UNAVAILABLE", str(error))
            except (PermanentBrokerError, BrokerContractError, ValueError) as error:
                self.repository.mark_submission_error(task.task_id, "CONTRACT_VALIDATION_FAILED", str(error))
            else:
                self.repository.mark_accepted(task.task_id, response)
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
            except (PermanentBrokerError, BrokerContractError, ValueError) as error:
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
