from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from knowledge_orchestrator.domain.broker_contracts import BrokerContractError
from knowledge_orchestrator.integrations.broker_client import BrokerClient, PermanentBrokerError, TransientBrokerError
from knowledge_orchestrator.repositories.semantic_repository import SemanticRepository

from .semantic_maintenance import SemanticContractError, SemanticMaintenanceService


class SemanticBrokerProcessor:
    def __init__(
        self,
        repository: SemanticRepository,
        service: SemanticMaintenanceService,
        client: BrokerClient,
        *,
        backoff_seconds: tuple[float, ...] = (30.0, 60.0, 120.0),
    ) -> None:
        self.repository = repository
        self.service = service
        self.client = client
        self.backoff_seconds = backoff_seconds

    async def dispatch_once(self) -> int:
        accepted = 0
        for candidate in self.repository.list_dispatchable_jobs():
            job = self.repository.claim_job(candidate.job_id)
            if job is None:
                continue
            try:
                response = await self.client.create_task(json.loads(job.request_json))
            except TransientBrokerError as error:
                retry_index = job.attempt - 1
                if retry_index < len(self.backoff_seconds):
                    retry_at = datetime.now(timezone.utc) + timedelta(seconds=self.backoff_seconds[retry_index])
                    self.repository.retry_job(job.job_id, next_retry_at=retry_at.isoformat(), message=str(error))
                else:
                    self.repository.fail_job(job.job_id, "BROKER_UNAVAILABLE", str(error))
            except (PermanentBrokerError, BrokerContractError, ValueError) as error:
                self.repository.fail_job(job.job_id, "CONTRACT_VALIDATION_FAILED", str(error))
            else:
                self.repository.accept_job(job.job_id, response)
                accepted += 1
        return accepted

    async def poll_once(self) -> int:
        updated = 0
        for job in self.repository.list_active_jobs():
            try:
                payload = await self.client.get_task(job.broker_task_id or job.job_id, status_url=job.status_url)
            except TransientBrokerError:
                continue
            except (PermanentBrokerError, BrokerContractError, ValueError) as error:
                self.repository.fail_job(job.job_id, "CONTRACT_VALIDATION_FAILED", str(error))
                updated += 1
                continue
            try:
                change = self.repository.update_job_status(job.job_id, payload)
                if change is None:
                    continue
                persisted, result_text = change
                if result_text is not None:
                    self.service.process_job_result(persisted, result_text)
                    self.repository.complete_job(job.job_id)
            except (SemanticContractError, ValueError) as error:
                self.repository.fail_job(job.job_id, "SEMANTIC_CONTRACT_FAILED", str(error))
            updated += 1
        return updated
