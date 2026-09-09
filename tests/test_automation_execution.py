from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace

from knowledge_orchestrator.domain.automation import AutomationDenied
from knowledge_orchestrator.domain.monitoring import SourceConfig
from knowledge_orchestrator.services.automation_execution import AutomationExecutionService
from knowledge_orchestrator.services.semantic_maintenance import SemanticMaintenanceService
from tests import test_automation_governance as governance


class AutomationExecutionTests(unittest.TestCase):
    setUp = governance.AutomationGovernanceTests.setUp
    tearDown = governance.AutomationGovernanceTests.tearDown
    publish_monitored = governance.AutomationGovernanceTests.publish_monitored
    extraction = staticmethod(governance.AutomationGovernanceTests.extraction)
    prepared = governance.AutomationGovernanceTests.prepared
    simulation = governance.AutomationGovernanceTests.simulation

    def authorize(self, repo, policy):
        policy = repo.set_enabled(policy['policy_id'], True, expected_revision=policy['revision'],
                                   expected_state_revision=policy['state_revision'], actor='human:owner',
                                   reason='Autorizar fuentes y límites de esta versión')
        control = repo.control()
        if control['paused']:
            repo.set_paused(False, expected_revision=control['revision'], actor='human:owner',
                            reason='Reanudar políticas explícitamente autorizadas')
        return policy

    def queue(self, repo, policy, candidate):
        simulation = self.simulation(repo, policy, candidate)
        return self.runtime.automation_execution.repository.queue(simulation['simulation_id'], actor='ui')

    def receipt(self, run):
        return self.runtime.automation_execution.repository.get(run['run_id'])

    def reservations(self):
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            return connection.execute('SELECT count(*) FROM automation_reservations').fetchone()[0]

    def test_disabled_policy_and_paused_control_cannot_queue_simulation(self):
        _, _, candidate, repo, policy, _ = self.prepared()
        with self.assertRaises(AutomationDenied):
            self.queue(repo, policy, candidate)
        policy = repo.set_enabled(policy['policy_id'], True, expected_revision=1, expected_state_revision=1,
                                   actor='human:owner', reason='Aprobar esta política')
        with self.assertRaises(AutomationDenied):
            self.queue(repo, policy, candidate)
        self.assertEqual(self.reservations(), 0)

    def test_approved_policy_publishes_once_with_original_history_and_attribution(self):
        old, _, candidate, repo, policy, _ = self.prepared()
        original = old.vault_path.read_text(encoding='utf-8')
        policy = self.authorize(repo, policy)
        run = self.queue(repo, policy, candidate)
        service = self.runtime.automation_execution
        self.assertTrue(service.run_next())
        self.assertEqual(self.receipt(run)['results'], {'APPLIED': 1})
        applied = self.runtime.semantic_repository.get_candidate(candidate.candidate_id)
        self.assertEqual(applied.automation_run_id, run['run_id'])
        self.assertEqual(applied.reviewed_by, f"policy:{policy['policy_id']}:revision:{policy['revision']}")
        self.assertIsNone(applied.review_batch_id)
        self.assertEqual(self.runtime.semantic_repository.revision_content(candidate.candidate_id), original)
        self.assertEqual(service.repository.queue(run['simulation_id'], actor='ui')['run_id'], run['run_id'])
        self.assertFalse(service.run_next())
        self.assertEqual(self.reservations(), 1)

    def test_pause_after_plan_before_intent_skips_without_changing_note(self):
        old, _, candidate, repo, policy, _ = self.prepared()
        before = old.vault_path.read_bytes()
        run = self.queue(repo, self.authorize(repo, policy), candidate)

        def pause(name):
            if name == 'automation_item_started':
                repo.set_paused(True, expected_revision=repo.control()['revision'], actor='human:owner',
                                reason='Detener antes de nueva intención')

        service = AutomationExecutionService(self.runtime.automation_execution.repository,
                                              self.runtime.semantic_maintenance, checkpoint=pause)
        service.run_next()
        self.assertEqual(self.receipt(run)['items'][0]['result']['reasons'], ['AUTOMATION_PAUSED'])
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(self.reservations(), 0)

    def test_editing_policy_revokes_queued_run_even_after_reauthorization(self):
        old, _, candidate, repo, policy, config = self.prepared()
        before = old.vault_path.read_bytes()
        policy = self.authorize(repo, policy)
        run = self.queue(repo, policy, candidate)
        updated = repo.update(policy['policy_id'], replace(config, min_confidence=0.97),
                              expected_revision=policy['revision'], expected_state_revision=policy['state_revision'],
                              actor='human:owner', reason='Nueva configuración')
        self.authorize(repo, updated)
        self.runtime.automation_execution.run_next()
        self.assertEqual(self.receipt(run)['items'][0]['result']['reasons'], ['POLICY_CHANGED'])
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(self.reservations(), 0)

    def test_source_revocation_after_simulation_is_revalidated_at_reservation(self):
        old, _, candidate, repo, policy, config = self.prepared()
        before = old.vault_path.read_bytes()
        run = self.queue(repo, self.authorize(repo, policy), candidate)
        source = self.runtime.sources.repository.get(config.source_ids[0])
        self.runtime.sources.repository.update(source['source_id'], SourceConfig(**{
            **source['config'], 'enabled': False}), expected_revision=source['revision'], actor='human:owner')
        self.runtime.automation_execution.run_next()
        self.assertIn('SOURCE_DISABLED', self.receipt(run)['items'][0]['result']['reasons'])
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(self.reservations(), 0)

    def test_manual_lock_added_after_simulation_is_absolute(self):
        old, _, candidate, repo, policy, _ = self.prepared()
        before = old.vault_path.read_bytes()
        run = self.queue(repo, self.authorize(repo, policy), candidate)
        self.runtime.semantic_repository.set_manual_lock(candidate.target_claim_id, True)
        self.runtime.automation_execution.run_next()
        self.assertEqual(self.receipt(run)['results'], {'CONFLICT': 1})
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(self.reservations(), 0)

    def test_quota_and_intent_roll_back_together_on_database_failure(self):
        old, _, candidate, repo, policy, _ = self.prepared()
        before = old.vault_path.read_bytes()
        run = self.queue(repo, self.authorize(repo, policy), candidate)
        with self.runtime.database.transaction() as connection:
            connection.execute("CREATE TRIGGER simulated_revision_failure BEFORE INSERT ON note_revisions "
                               "BEGIN SELECT RAISE(ABORT,'simulated database failure'); END")
        self.runtime.automation_execution.run_next()
        self.assertEqual(self.receipt(run)['results'], {'FAILED': 1})
        self.assertEqual(self.reservations(), 0)
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate.candidate_id).status,
                         'PENDING_REVIEW')

    def test_concurrent_runs_cannot_exceed_daily_quota(self):
        _, _, a, repo, policy, config = self.prepared()
        _, _, b, _, _, other = self.prepared(label='Y', key='policy-create-002')
        policy = repo.update(policy['policy_id'], replace(config, source_ids=(*config.source_ids, *other.source_ids),
                                                         max_tasks_per_run=1, max_tasks_per_day=1),
                             expected_revision=1, expected_state_revision=1, actor='human:owner', reason='Una al día')
        policy = self.authorize(repo, policy)
        runs = [self.queue(repo, policy, candidate) for candidate in (a, b)]
        service = self.runtime.automation_execution
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: service.run_next(), range(2)))
        self.assertEqual(outcomes, [True, True])
        self.assertEqual(self.reservations(), 1)
        statuses = [self.receipt(run)['items'][0] for run in runs]
        self.assertEqual(sorted(item['status'] for item in statuses), ['APPLIED', 'SKIPPED'])
        self.assertEqual(next(item for item in statuses if item['status'] == 'SKIPPED')['result']['reasons'],
                         ['DAILY_TASK_LIMIT'])

    def test_recovery_finishes_reserved_publication_after_pause_without_duplicate_quota(self):
        _, _, candidate, repo, policy, _ = self.prepared()
        run = self.queue(repo, self.authorize(repo, policy), candidate)

        def crash(name):
            if name == 'semantic_intent':
                raise RuntimeError('Simulated crash after authorized intent')

        service = AutomationExecutionService(self.runtime.automation_execution.repository,
                                              SemanticMaintenanceService(self.runtime.semantic_repository,
            note_editor=self.runtime.semantic_maintenance.note_editor,
                                                                         checkpoint=crash))
        service.run_next()
        self.assertEqual(self.receipt(run)['status'], 'RECOVERY_REQUIRED')
        self.assertEqual(self.reservations(), 1)
        repo.set_paused(True, expected_revision=repo.control()['revision'], actor='human:owner',
                        reason='Detener nuevas aplicaciones')
        self.runtime.recover_once(ingest_inbox=False)
        self.runtime.automation_execution.run_next()
        self.assertEqual(self.receipt(run)['results'], {'APPLIED': 1})
        self.assertEqual(self.reservations(), 1)
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM note_revisions').fetchone()[0], 1)

    def test_crash_after_application_before_receipt_keeps_exactly_one_successor(self):
        _, _, candidate, repo, policy, _ = self.prepared()
        run = self.queue(repo, self.authorize(repo, policy), candidate)

        def crash(name):
            if name == 'automation_applied_before_receipt':
                raise RuntimeError('Simulated receipt failure')

        service = AutomationExecutionService(self.runtime.automation_execution.repository,
                                              self.runtime.semantic_maintenance, checkpoint=crash)
        with self.assertRaises(RuntimeError):
            service.run_next()
        self.runtime.recover_once(ingest_inbox=False)
        self.runtime.automation_execution.run_next()
        self.assertEqual(self.receipt(run)['results'], {'APPLIED': 1})
        self.assertEqual(self.reservations(), 1)
        self.assertEqual(len(self.runtime.semantic_repository.list_claims()), 3)

    def test_first_task_conflict_does_not_prevent_independent_task_success(self):
        old_a, new_a, a, repo, policy, config = self.prepared()
        old_b, _, b, _, _, other = self.prepared(label='Y', key='policy-create-002')
        before_a, before_b = old_a.vault_path.read_bytes(), old_b.vault_path.read_bytes()
        policy = repo.update(policy['policy_id'], replace(config, source_ids=(*config.source_ids, *other.source_ids)),
                             expected_revision=1, expected_state_revision=1, actor='human:owner', reason='Dos fuentes')
        policy = self.authorize(repo, policy)
        simulation = self.runtime.automation_simulation.simulate(policy['policy_id'],
            expected_revision=policy['revision'], actor='ui', selection=[{
                'candidate_id': c.candidate_id, 'expected_revision': c.proposal_revision} for c in (a, b)])
        run = self.runtime.automation_execution.repository.queue(simulation['simulation_id'], actor='ui')
        new_a.vault_path.write_text('Evidencia cambiada después de simular', encoding='utf-8')
        self.runtime.automation_execution.run_next()
        self.assertEqual(self.receipt(run)['results'], {'CONFLICT': 1, 'APPLIED': 1})
        self.assertEqual(old_a.vault_path.read_bytes(), before_a)
        self.assertNotEqual(old_b.vault_path.read_bytes(), before_b)
        self.assertEqual(self.reservations(), 1)

    def test_pause_then_resume_does_not_reauthorize_old_queued_plan(self):
        old, _, candidate, repo, policy, _ = self.prepared()
        before = old.vault_path.read_bytes()
        run = self.queue(repo, self.authorize(repo, policy), candidate)
        repo.set_paused(True, expected_revision=2, actor='human:owner', reason='Pausar')
        repo.set_paused(False, expected_revision=3, actor='human:owner', reason='Reanudar nuevos planes')
        self.runtime.automation_execution.run_next()
        self.assertEqual(self.receipt(run)['items'][0]['result']['reasons'], ['CONTROL_CHANGED'])
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(self.reservations(), 0)

    def test_crash_before_intent_then_pause_does_not_publish_on_recovery(self):
        old, _, candidate, repo, policy, _ = self.prepared()
        before = old.vault_path.read_bytes()
        run = self.queue(repo, self.authorize(repo, policy), candidate)

        def crash(name):
            if name == 'automation_item_started':
                raise RuntimeError('Simulated interruption before intent')

        service = AutomationExecutionService(self.runtime.automation_execution.repository,
                                              self.runtime.semantic_maintenance, checkpoint=crash)
        with self.assertRaises(RuntimeError):
            service.run_next()
        repo.set_paused(True, expected_revision=2, actor='human:owner', reason='Detener')
        self.runtime.recover_once(ingest_inbox=False)
        self.runtime.automation_execution.run_next()
        self.assertEqual(self.receipt(run)['results'], {'SKIPPED': 1})
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(self.reservations(), 0)

    def test_policy_edit_does_not_reset_daily_usage(self):
        _, _, candidate, repo, policy, config = self.prepared()
        policy = self.authorize(repo, policy)
        self.queue(repo, policy, candidate)
        self.runtime.automation_execution.run_next()
        policy = repo.update(policy['policy_id'], replace(config, max_tasks_per_run=1, max_tasks_per_day=1),
                             expected_revision=policy['revision'], expected_state_revision=policy['state_revision'],
                             actor='human:owner', reason='Limitar a una por día')
        policy = self.authorize(repo, policy)
        forecast = self.runtime.automation_simulation.simulate(policy['policy_id'],
            expected_revision=policy['revision'], actor='ui', selection=[])['plan']
        self.assertEqual(forecast['daily_usage'], 1)
        self.assertEqual(forecast['daily_remaining'], 0)
        self.assertTrue(forecast['daily_quota_evaluated'])
