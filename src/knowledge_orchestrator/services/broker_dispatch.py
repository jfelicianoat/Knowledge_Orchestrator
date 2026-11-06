from __future__ import annotations

from collections.abc import Collection

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
        max_in_flight: int | None = None,
    ) -> None:
        self.repository = repository
        self.client = client
        self.backoff_seconds = backoff_seconds
        self.max_in_flight = max_in_flight

    async def dispatch_once(self, task_ids: Collection[str] | None = None) -> int:
        accepted = 0
        candidates = self.repository.list_dispatchable()
        if task_ids is not None:
            # Lo que pide la persona desde la UI sale aunque el cupo esté lleno.
            selected = set(task_ids)
            candidates = [candidate for candidate in candidates if candidate.task_id in selected]
        elif self.max_in_flight is not None:
            # Cupo en el Broker: van saliendo en orden de creación, así la síntesis de un
            # documento empezado pasa antes que los fragmentos de los siguientes.
            room = self.max_in_flight - self.repository.count_in_flight()
            candidates = candidates[:max(0, room)]
        for candidate in candidates:
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
                # attempt_broker_submission siempre fija retry_at y message en
                # kind="retry"; el assert documenta y tipa la invariante.
                assert decision.retry_at is not None
                self.repository.release_submission(
                    task.task_id,
                    next_retry_at=decision.retry_at,
                    message=decision.message or "",
                )
            elif decision.kind == "exhausted":
                self.repository.mark_submission_error(task.task_id, "BROKER_UNAVAILABLE", decision.message or "")
            elif decision.kind == "permanent":
                self.repository.mark_submission_error(task.task_id, decision.code, decision.message or "")
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
                    operation_id=task.idempotency_key,
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
            # Una respuesta que no se sabe aplicar cierra SU tarea y el sondeo sigue:
            # antes la excepción cortaba el ciclo y las demás no se consultaban nunca.
            try:
                if self.repository.apply_status(task.task_id, payload):
                    updated += 1
                    self.planner.advance_workflow(task.workflow_id)
            except Exception as error:  # frontera por tarea
                self.repository.mark_submission_error(
                    task.task_id, "STATUS_APPLY_FAILED", f"{type(error).__name__}: {error}",
                )
                updated += 1
        return updated
