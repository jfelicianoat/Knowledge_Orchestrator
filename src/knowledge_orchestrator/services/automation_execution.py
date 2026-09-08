"""Ejecución por política con autorización/cupos reservados al iniciar cada publicación."""
from __future__ import annotations

from collections.abc import Callable

from knowledge_orchestrator.domain.automation import AutomationDenied
from knowledge_orchestrator.repositories.automation_run_repository import AutomationRunRepository
from knowledge_orchestrator.services.semantic_maintenance import SemanticMaintenanceService


class AutomationExecutionService:
    def __init__(self, repository: AutomationRunRepository, maintenance: SemanticMaintenanceService, *,
                 checkpoint: Callable[[str], None] | None = None) -> None:
        self.repository, self.maintenance = repository, maintenance
        self.checkpoint = checkpoint or (lambda _name: None)

    def run_next(self) -> bool:
        run = self.repository.claim_next()
        if run is None:
            return False
        try:
            self._run(run)
        except Exception:
            self.repository.pause_for_recovery(run['run_id'])
            raise
        return True

    def _run(self, run: dict) -> None:
        run_id = run['run_id']
        actor = f"policy:{run['policy_id']}:revision:{run['policy_revision']}"
        for item in run['items']:
            if item['status'] != 'PENDING':
                continue
            identifier = item['candidate_id']
            self.repository.start_item(run_id, identifier)
            self.checkpoint('automation_item_started')
            candidate = self.maintenance.repository.get_candidate(identifier)
            result: dict
            if candidate and candidate.automation_run_id == run_id and candidate.status == 'APPLYING':
                self.repository.pause_for_recovery(run_id)
                return
            if candidate and candidate.automation_run_id == run_id and candidate.status == 'APPLIED':
                status, result = 'APPLIED', {'successor_id': candidate.applied_successor_id, 'recovered': True}
            elif candidate is None or candidate.status in {'APPLIED', 'REJECTED', 'APPLYING'}:
                status, result = 'EXTERNALLY_RESOLVED', {'reasons': ['RESOLVED_OUTSIDE_RUN']}
            else:
                try:
                    applied = self.maintenance.approve(identifier, expected_revision=item['proposal_revision'],
                                                        actor=actor, automation_run_id=run_id)
                    status, result = 'APPLIED', {'successor_id': applied.applied_successor_id}
                except AutomationDenied as error:
                    status, result = 'SKIPPED', {'reasons': error.reasons}
                except Exception as error:
                    current = self.maintenance.repository.get_candidate(identifier)
                    if current is not None and current.status == 'APPLYING':
                        self.repository.pause_for_recovery(run_id)
                        return
                    status = 'CONFLICT' if isinstance(error, ValueError) else 'FAILED'
                    reason = str(error) if isinstance(error, ValueError) else 'No se pudo aplicar la propuesta'
                    result = {'reason': reason}
            self.checkpoint('automation_applied_before_receipt')
            self.repository.finish_item(run_id, identifier, status=status, result=result)
        self.repository.finish_run(run_id)
