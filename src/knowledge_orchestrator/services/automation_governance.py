"""Operaciones explícitas de API/UI; simular nunca activa ni publica."""
from __future__ import annotations

import json
import re

from knowledge_orchestrator.repositories.automation_governance_repository import AutomationGovernanceRepository
from knowledge_orchestrator.repositories.automation_schedule_repository import AutomationScheduleRepository
from knowledge_orchestrator.services.automation_simulation import AutomationSimulationService


class AutomationGovernanceService:
    def __init__(self, simulation: AutomationSimulationService) -> None:
        self.simulation = simulation
        self.policies = simulation.repository
        self.repository = AutomationGovernanceRepository(self.policies)

    def simulate(self, policy_id: int, *, expected_revision: int, actor: str, key: str,
                 selection: list[dict] | None = None) -> dict:
        self.policies._actor(actor, 'Simulación solicitada')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,200}', key):
            raise ValueError('La simulación requiere clave idempotente')
        payload = json.dumps({'policy_id': policy_id, 'expected_revision': expected_revision,
                              'selection': selection}, sort_keys=True, allow_nan=False)
        previous = self.repository.previous(actor, key, payload)
        if previous:
            return self.policies.simulation(previous)
        preview = self.simulation.simulate(policy_id, expected_revision=expected_revision, actor=actor,
                                            selection=selection, persist=False)
        return self.repository.save(actor, key, payload, preview)

    def set_enabled(self, policy_id: int, enabled: bool, *, expected_revision: int, expected_state_revision: int,
                    actor: str, reason: str, reviewed_simulation_id: str | None = None) -> dict:
        if enabled and not reviewed_simulation_id:
            raise ValueError('Autorizar requiere identificar la simulación revisada')
        return self.policies.set_enabled(policy_id, enabled, expected_revision=expected_revision,
                                         expected_state_revision=expected_state_revision, actor=actor, reason=reason,
                                         reviewed_simulation_id=reviewed_simulation_id)

    def simulate_page(self, policy_id: int, *, expected_revision: int, actor: str, key: str,
                      after_candidate_id: int = 0, limit: int = 100) -> dict:
        """Página UI con ámbito e identidad estables ante reintentos y nuevas propuestas."""
        self.policies._actor(actor, 'Simulación por página')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,200}', key) \
                or type(after_candidate_id) is not int or not 0 <= after_candidate_id <= 2**63 - 1 \
                or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Solicitud de página inválida')
        payload = json.dumps({'mode': 'policy_page', 'policy_id': policy_id, 'expected_revision': expected_revision,
                              'after_candidate_id': after_candidate_id, 'limit': limit}, sort_keys=True)
        previous = self.repository.previous(actor, key, payload)
        if previous:
            return self.policies.simulation(previous)
        policy = self.policies.get(policy_id)
        selection, _cursor = AutomationScheduleRepository(self.repository.database).selection(
            {'config_json': json.dumps(policy['config']), 'candidate_cursor': after_candidate_id},
            limit=limit, wrap=False)
        preview = self.simulation.simulate(policy_id, expected_revision=expected_revision, actor=actor,
                                            selection=selection, persist=False)
        preview['plan']['selection_page'] = {'after_candidate_id': after_candidate_id, 'limit': limit}
        return self.repository.save(actor, key, payload, preview)
