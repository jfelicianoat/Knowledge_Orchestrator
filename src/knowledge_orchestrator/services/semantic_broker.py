from __future__ import annotations

from knowledge_orchestrator.domain.broker_contracts import BrokerContractError
from knowledge_orchestrator.integrations.broker_client import BrokerClient, PermanentBrokerError, TransientBrokerError
from knowledge_orchestrator.repositories.semantic_repository import SemanticRepository

from .broker_submission import attempt_broker_submission
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
            decision = await attempt_broker_submission(
                self.client,
                job.request_json,
                attempt=job.attempt,
                backoff_seconds=self.backoff_seconds,
            )
            if decision.kind == "retry":
                assert decision.retry_at is not None
                self.repository.retry_job(
                    job.job_id, next_retry_at=decision.retry_at, message=decision.message or ""
                )
            elif decision.kind == "exhausted":
                self.repository.fail_job(job.job_id, "BROKER_UNAVAILABLE", decision.message or "")
            elif decision.kind == "permanent":
                self.repository.fail_job(job.job_id, "CONTRACT_VALIDATION_FAILED", decision.message or "")
            else:
                self.repository.accept_job(job.job_id, decision.response or {})
                accepted += 1
        return accepted

    async def poll_once(self) -> int:
        updated = 0
        for job in self.repository.list_active_jobs():
            try:
                payload = await self.client.get_task(job.broker_task_id or job.job_id, status_url=job.status_url)
            except TransientBrokerError:
                continue
            except (PermanentBrokerError, BrokerContractError) as error:
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
