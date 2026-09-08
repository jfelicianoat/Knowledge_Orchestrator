"""Simulación auditable. No crea intenciones, no aprueba propuestas ni publica notas."""
from __future__ import annotations

import json
from contextlib import closing

from knowledge_orchestrator.domain.automation import AutomationPlanTooLarge, AutomationPolicyConfig
from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.repositories.automation_guards import policy_blockers
from knowledge_orchestrator.repositories.automation_repository import AutomationRepository
from knowledge_orchestrator.services.semantic_maintenance import SemanticMaintenanceService


class AutomationSimulationService:
    def __init__(self, repository: AutomationRepository, maintenance: SemanticMaintenanceService) -> None:
        self.repository, self.maintenance = repository, maintenance

    def simulate(self, policy_id: int, *, expected_revision: int, actor: str,
                 selection: list[dict] | None = None, persist: bool = True) -> dict:
        policy, control = self.repository.get(policy_id), self.repository.control()
        if type(expected_revision) is not int or policy['revision'] != expected_revision:
            raise KnowledgeConflict('La política cambió desde que se abrió')
        config = AutomationPolicyConfig(**policy['config'])
        with closing(self.repository.database.connect(readonly=True)) as connection:
            used_today = connection.execute('SELECT count(*) FROM automation_reservations WHERE policy_id=? '
                                            "AND utc_day=strftime('%Y-%m-%d','now')", (policy_id,)).fetchone()[0]
        remaining_today = max(0, config.max_tasks_per_day - used_today)
        if selection is None:
            with closing(self.repository.database.connect(readonly=True)) as connection:
                selection = [dict(row) for row in connection.execute(
                    'SELECT candidate_id,proposal_revision AS expected_revision FROM update_candidates '
                    "WHERE status IN ('PENDING_COMPARISON','PENDING_REVIEW','CONFLICT') "
                    'ORDER BY candidate_id LIMIT 1001')]
        if not isinstance(selection, list) or len(selection) > 1000:
            raise ValueError('Selecciona como máximo 1000 propuestas')
        for item in selection:
            if not isinstance(item, dict) or set(item) != {'candidate_id', 'expected_revision'} \
                    or type(item['candidate_id']) is not int or item['candidate_id'] <= 0 \
                    or type(item['expected_revision']) is not int or item['expected_revision'] < 0:
                raise ValueError('Selección de propuestas inválida')
        if len({item['candidate_id'] for item in selection}) != len(selection):
            raise ValueError('La selección contiene propuestas duplicadas')
        items, size = [], 0
        for selected in sorted(selection, key=lambda item: item['candidate_id']):
            item = self.maintenance.preview_application(selected['candidate_id'],
                                                        expected_revision=selected['expected_revision'])
            if item['eligible']:
                item['blockers'].extend(self._policy_blockers(config, item))
            item['eligible'] = item['eligible'] and not item['blockers']
            size += len(json.dumps(item, ensure_ascii=False, allow_nan=False).encode())
            if size > 8 * 1024 * 1024:
                raise AutomationPlanTooLarge()
            items.append(item)
        # Ninguna simulación debe sugerir aplicar simultáneamente notas interdependientes.
        eligible = [item for item in items if item['eligible']]
        for index, item in enumerate(eligible):
            for other in eligible[index + 1:]:
                if item['target_note_id'] == other['target_note_id'] \
                        or item['target_note_id'] in other['evidence_note_ids'] \
                        or other['target_note_id'] in item['evidence_note_ids']:
                    for dependent in (item, other):
                        dependent['eligible'] = False
                        if 'DEPENDENT_NOTE_UPDATES' not in dependent['blockers']:
                            dependent['blockers'].append('DEPENDENT_NOTE_UPDATES')
        eligible = [item for item in items if item['eligible']]
        for index, item in enumerate(eligible):
            if index >= config.max_tasks_per_run or index >= remaining_today:
                item['eligible'] = False
                item['blockers'].append('RUN_TASK_LIMIT' if index >= config.max_tasks_per_run else 'DAILY_TASK_LIMIT')
        gates = []
        if not policy['enabled']:
            gates.append('POLICY_DISABLED')
        if control['paused']:
            gates.append('AUTOMATION_PAUSED')
        plan = {'mode': 'dry_run', 'publication_authorized': False, 'items': items,
                'execution_gates': gates, 'limits_reserved': False, 'daily_quota_evaluated': True,
                'daily_usage': used_today, 'daily_remaining': remaining_today, 'quota_timezone': 'UTC',
                'counts': {'tasks': len(items), 'eligible': sum(bool(item['eligible']) for item in items)},
                'policy': {'policy_id': policy_id, 'revision': policy['revision'],
                           'state_revision': policy['state_revision'], 'config': policy['config']}}
        if len(json.dumps(plan, ensure_ascii=False, allow_nan=False).encode()) > 8 * 1024 * 1024:
            raise AutomationPlanTooLarge()
        if not persist:
            return {'policy': policy, 'control': control, 'plan': plan}
        return self.repository.save_simulation(policy, control, plan, actor=actor)

    def _policy_blockers(self, config: AutomationPolicyConfig, preview: dict) -> list[str]:
        with closing(self.repository.database.connect(readonly=True)) as connection:
            connection.execute('BEGIN')
            candidate = connection.execute('SELECT * FROM update_candidates WHERE candidate_id=?',
                                           (preview['candidate_id'],)).fetchone()
            if candidate is None or candidate['proposal_revision'] != preview['revision']:
                return ['PROPOSAL_CHANGED']
            blockers, source = policy_blockers(connection, config, candidate)
        if source is not None:
            preview['policy_source'] = source
        return blockers
