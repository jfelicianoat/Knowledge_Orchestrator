from __future__ import annotations

import sqlite3
import unittest
from contextlib import closing
from dataclasses import replace
from unittest.mock import patch

from knowledge_orchestrator.domain.automation import AutomationPolicyConfig
from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.domain.monitoring import SourceConfig
from knowledge_orchestrator.repositories.automation_repository import AutomationRepository
from knowledge_orchestrator.services.automation_simulation import AutomationSimulationService
from knowledge_orchestrator.services.provenance import source_provenance
from tests import test_phase_six_semantic_maintenance as phase_six
from tests import test_phase_twelve_knowledge_maintenance as phase_twelve


class AutomationGovernanceTests(unittest.TestCase):
    setUp = phase_six.PhaseSixSemanticMaintenanceTests.setUp
    tearDown = phase_six.PhaseSixSemanticMaintenanceTests.tearDown
    publish = phase_six.PhaseSixSemanticMaintenanceTests.publish
    extraction = staticmethod(phase_six.PhaseSixSemanticMaintenanceTests.extraction)
    prepare_candidate = phase_six.PhaseSixSemanticMaintenanceTests.prepare_candidate
    publish_monitored = phase_twelve.PhaseTwelveKnowledgeMaintenanceTests.publish_monitored

    def prepared(self, *, relation='SUPERSEDES', trust=95, role='official_documentation',
                 label='X', key='policy-create-001'):
        entity = f'Producto {label}'
        old_text, new_text = f'{entity} versión 1.', f'{entity} versión 2.'
        old = self.publish_monitored(old_text, trust_level=95, source_role='official_documentation')
        new = self.publish_monitored(new_text, trust_level=trust, source_role=role)
        service = self.runtime.semantic_maintenance
        service.ingest_extraction(old.note_id, self.extraction(old, old_text, entities=(entity,)))
        candidate_id = service.ingest_extraction(new.note_id, self.extraction(new, new_text, entities=(entity,)))[0]
        candidate = service.compare(candidate_id, {'relation': relation, 'confidence': 0.99, 'impact': 'HIGH',
                                                   'rationale': 'Nueva versión explícita.',
                                                   'replacement_text': new_text})
        source_id = source_provenance(self.runtime.database, new.capture_id)['monitoring']['monitored_source_id']
        repository = AutomationRepository(self.runtime.database)
        config = AutomationPolicyConfig('Versiones oficiales', (source_id,))
        policy = repository.create(config, actor='ui', key=key)
        return old, new, candidate, repository, policy, config

    def simulation(self, repository, policy, candidate):
        return AutomationSimulationService(repository, self.runtime.semantic_maintenance).simulate(
            policy['policy_id'], expected_revision=policy['revision'], actor='ui', selection=[{
                'candidate_id': candidate.candidate_id, 'expected_revision': candidate.proposal_revision}])

    def test_policy_requires_explicit_scope_and_cannot_allow_contradictions(self):
        for payload in ({'source_ids': ()}, {'source_ids': (True,)}, {'relations': ('CONTRADICTS',)},
                        {'min_confidence': float('nan')}, {'min_source_trust': True},
                        {'max_tasks_per_run': 25, 'max_tasks_per_day': 20}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                AutomationPolicyConfig(**{'name': 'Política', 'source_ids': (1,), **payload})
        sources = [2, 1]
        config = AutomationPolicyConfig('Política', sources)
        sources.append(3)
        self.assertEqual(config.source_ids, (1, 2))
        repo = AutomationRepository(self.runtime.database)
        with self.assertRaises(ValueError):
            repo.create(config, actor='ui', key='missing-source')

    def test_creation_is_disabled_idempotent_and_global_control_is_paused(self):
        old, _, _, repo, policy, config = self.prepared()
        before = old.vault_path.read_bytes()
        self.assertFalse(policy['enabled'])
        self.assertIsNone(policy['approved_by'])
        self.assertEqual(repo.control(), {'revision': 1, 'paused': True})
        self.assertEqual(repo.create(config, actor='ui', key='policy-create-001')['policy_id'], policy['policy_id'])
        with self.assertRaises(KnowledgeConflict):
            repo.create(replace(config, name='Otra'), actor='ui', key='policy-create-001')
        self.assertEqual(old.vault_path.read_bytes(), before)

    def test_edit_revokes_activation_and_preserves_immutable_versions_and_decisions(self):
        _, _, _, repo, policy, config = self.prepared()
        enabled = repo.set_enabled(policy['policy_id'], True, expected_revision=1, expected_state_revision=1,
                                   actor='human:owner', reason='Autorización para estas fuentes y límites')
        self.assertTrue(enabled['enabled'])
        self.assertEqual(enabled['approved_by'], 'human:owner')
        with self.assertRaises(KnowledgeConflict):
            repo.set_enabled(policy['policy_id'], False, expected_revision=1, expected_state_revision=1,
                             actor='human:stale', reason='Lectura anterior')
        updated = repo.update(policy['policy_id'], replace(config, min_confidence=0.97), expected_revision=1,
                              expected_state_revision=2, actor='human:owner', reason='Mayor umbral')
        self.assertEqual(updated['revision'], 2)
        self.assertFalse(updated['enabled'])
        self.assertIsNone(updated['approved_by'])
        history = repo.history(policy['policy_id'])
        self.assertEqual([row['config']['min_confidence'] for row in history['versions']], [0.95, 0.97])
        self.assertEqual([row['enabled'] for row in history['decisions']], [0, 1, 0])
        with closing(self.runtime.database.connect()) as connection:
            for table in ('automation_policy_versions', 'automation_policy_decisions'):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(f'DELETE FROM {table}')

    def test_global_control_requires_explicit_actor_and_revision_and_preserves_history(self):
        repo = AutomationRepository(self.runtime.database)
        with self.assertRaises(ValueError):
            repo.set_paused(False, expected_revision=1, actor='', reason='Activar')
        self.assertEqual(repo.set_paused(False, expected_revision=1, actor='human:owner',
                                         reason='Permitir solo políticas aprobadas'), {'revision': 2, 'paused': False})
        with self.assertRaises(KnowledgeConflict):
            repo.set_paused(False, expected_revision=1, actor='human:stale', reason='Lectura anterior')
        repo.set_paused(True, expected_revision=2, actor='human:owner', reason='Detener nuevas aplicaciones')
        self.assertTrue(repo.control()['paused'])
        with closing(self.runtime.database.connect()) as connection:
            self.assertEqual([row[0] for row in connection.execute(
                'SELECT paused FROM automation_control_history ORDER BY revision')], [1, 0, 1])
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('UPDATE automation_control_history SET paused=0')

    def test_simulation_keeps_evidence_and_never_publishes_or_reserves_an_intent(self):
        old, _, candidate, repo, policy, _ = self.prepared()
        before = old.vault_path.read_bytes()
        simulation = self.simulation(repo, policy, candidate)
        plan = simulation['plan']
        self.assertEqual(plan['counts'], {'tasks': 1, 'eligible': 1})
        self.assertEqual(plan['execution_gates'], ['POLICY_DISABLED', 'AUTOMATION_PAUSED'])
        self.assertFalse(plan['publication_authorized'])
        self.assertFalse(plan['limits_reserved'])
        self.assertEqual(len(plan['items'][0]['assessment']['evidence']), 2)
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate.candidate_id), candidate)
        enabled = repo.set_enabled(policy['policy_id'], True, expected_revision=1, expected_state_revision=1,
                                   actor='human:owner', reason='Aprobar esta configuración')
        repo.set_paused(False, expected_revision=1, actor='human:owner', reason='Autorizar políticas aprobadas')
        enabled_plan = self.simulation(repo, enabled, candidate)['plan']
        self.assertEqual(enabled_plan['execution_gates'], [])
        self.assertFalse(enabled_plan['publication_authorized'])
        self.assertEqual(old.vault_path.read_bytes(), before)
        with closing(self.runtime.database.connect()) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM note_revisions').fetchone()[0], 0)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE automation_simulations SET plan_json='{}'")

    def test_manual_lock_and_external_evidence_change_exclude_simulation(self):
        old, new, candidate, repo, policy, _ = self.prepared()
        before = old.vault_path.read_bytes()
        self.runtime.semantic_repository.set_manual_lock(candidate.target_claim_id, True)
        self.assertEqual(self.simulation(repo, policy, candidate)['plan']['counts']['eligible'], 0)
        self.runtime.semantic_repository.set_manual_lock(candidate.target_claim_id, False)
        new.vault_path.write_text('Evidencia modificada', encoding='utf-8')
        self.assertEqual(self.simulation(repo, policy, candidate)['plan']['counts']['eligible'], 0)
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate.candidate_id).status,
                         'PENDING_REVIEW')

    def test_contradictory_or_lower_trust_source_never_becomes_eligible_by_high_confidence(self):
        _, _, candidate, repo, policy, _ = self.prepared(relation='CONTRADICTS')
        item = self.simulation(repo, policy, candidate)['plan']['items'][0]
        self.assertFalse(item['eligible'])
        self.assertIn('RELATION_NOT_ALLOWED', item['blockers'])
        self.assertIn('CLAIM_NOT_CURRENT', item['blockers'])

    def test_changed_source_configuration_invalidates_snapshot_trust(self):
        _, _, candidate, repo, policy, config = self.prepared()
        source = self.runtime.sources.repository.get(config.source_ids[0])
        self.runtime.sources.repository.update(source['source_id'], SourceConfig(**{
            **source['config'], 'trust_level': 10, 'source_role': 'secondary', 'enabled': False}),
            expected_revision=source['revision'], actor='human:owner')
        item = self.simulation(repo, policy, candidate)['plan']['items'][0]
        self.assertFalse(item['eligible'])
        self.assertTrue({'SOURCE_REVISION_CHANGED', 'SOURCE_DISABLED', 'SOURCE_ROLE_NOT_ALLOWED',
                         'SOURCE_TRUST_BELOW_POLICY'} <= set(item['blockers']))

    def test_policy_change_during_simulation_requires_new_review(self):
        _, _, candidate, repo, policy, config = self.prepared()
        original = repo.save_simulation

        def concurrent_edit(policy, control, plan, *, actor):
            repo.update(policy['policy_id'], replace(config, name='Revisada'), expected_revision=1,
                        expected_state_revision=1, actor='human:other', reason='Edición simultánea')
            return original(policy, control, plan, actor=actor)

        with patch.object(repo, 'save_simulation', side_effect=concurrent_edit), self.assertRaises(KnowledgeConflict):
            self.simulation(repo, policy, candidate)
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM automation_simulations').fetchone()[0], 0)

    def test_simulation_limits_independent_tasks_without_consuming_daily_quota(self):
        old_a, _, a, repo, policy, config = self.prepared()
        old_b, _, b, _, _, other_config = self.prepared(label='Y', key='policy-create-002')
        original_a, original_b = old_a.vault_path.read_bytes(), old_b.vault_path.read_bytes()
        updated = repo.update(policy['policy_id'], replace(config, source_ids=(*config.source_ids,
                                                                              *other_config.source_ids),
                                                          max_tasks_per_run=1), expected_revision=1,
                              expected_state_revision=1, actor='human:owner', reason='Una tarea por ejecución')
        result = self.runtime.automation_simulation.simulate(policy['policy_id'], expected_revision=updated['revision'],
                                                             actor='ui', selection=[
            {'candidate_id': c.candidate_id, 'expected_revision': c.proposal_revision} for c in (a, b)])
        self.assertEqual(result['plan']['counts'], {'tasks': 2, 'eligible': 1})
        self.assertIn('RUN_TASK_LIMIT', result['plan']['items'][1]['blockers'])
        self.assertTrue(result['plan']['daily_quota_evaluated'])
        self.assertFalse(result['plan']['limits_reserved'])
        self.assertEqual(old_a.vault_path.read_bytes(), original_a)
        self.assertEqual(old_b.vault_path.read_bytes(), original_b)
