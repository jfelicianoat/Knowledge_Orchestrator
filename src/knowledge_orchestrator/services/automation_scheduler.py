"""Planifica solo políticas autorizadas; la ejecución conserva sus guardas por tarea."""
from __future__ import annotations

from knowledge_orchestrator.domain.automation import AutomationPlanTooLarge
from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.repositories.automation_schedule_repository import AutomationScheduleRepository
from knowledge_orchestrator.services.automation_execution import AutomationExecutionService
from knowledge_orchestrator.services.automation_simulation import AutomationSimulationService


class AutomationScheduler:
    def __init__(self, repository: AutomationScheduleRepository, simulation: AutomationSimulationService,
                 execution: AutomationExecutionService) -> None:
        self.repository, self.simulation, self.execution = repository, simulation, execution

    def tick(self) -> bool:
        # Los recibos pendientes se reconcilian aun en pausa; nuevas intenciones la comprueban.
        if self.execution.run_next():
            return True
        job = self.repository.lease_due()
        if job is None:
            return False
        try:
            selection, cursor = self.repository.selection(job)
            while True:
                try:
                    preview = self.simulation.simulate(job['policy_id'], expected_revision=job['policy_revision'],
                                                       actor='scheduler', selection=selection, persist=False)
                    break
                except AutomationPlanTooLarge:
                    if len(selection) <= 1:
                        self.repository.failed(job, 'PLAN_TOO_LARGE',
                                               oversized_candidate=selection[0] if selection else None)
                        return True
                    selection = selection[:len(selection) // 2]
                    cursor = selection[-1]['candidate_id']
            self.repository.finish(job, preview, cursor)
        except KnowledgeConflict:
            self.repository.failed(job, 'AUTHORIZATION_CHANGED')
        except Exception:
            self.repository.failed(job, 'EVALUATION_FAILED')
        return True
