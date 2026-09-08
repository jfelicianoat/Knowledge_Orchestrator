from __future__ import annotations

import sqlite3
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from unittest.mock import patch

from knowledge_orchestrator.domain.automation import AutomationDenied, AutomationPlanTooLarge
from knowledge_orchestrator.repositories.automation_schedule_repository import AutomationScheduleRepository
from knowledge_orchestrator.services.automation_scheduler import AutomationScheduler
from knowledge_orchestrator.services.operations_status import OperationsStatusService
from tests import test_automation_execution as execution


class AutomationSchedulerTests(unittest.TestCase):
    setUp = execution.AutomationExecutionTests.setUp
    tearDown = execution.AutomationExecutionTests.tearDown
    publish_monitored = execution.AutomationExecutionTests.publish_monitored
    extraction = staticmethod(execution.AutomationExecutionTests.extraction)
    prepared = execution.AutomationExecutionTests.prepared
    authorize = execution.AutomationExecutionTests.authorize
    reservations = execution.AutomationExecutionTests.reservations

    def counts(self):
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            return tuple(connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                         for table in ('automation_simulations', 'automation_runs', 'automation_reservations'))

    def schedule(self, policy):
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            return dict(connection.execute('SELECT * FROM automation_schedules WHERE policy_id=?',
                                           (policy['policy_id'],)).fetchone())

    def due(self):
        with self.runtime.database.transaction() as connection:
            connection.execute('UPDATE automation_schedules SET next_check_at=0')

    def preview(self, job):
        scheduler = self.runtime.automation_scheduler
        selected, cursor = scheduler.repository.selection(job)
        return scheduler.simulation.simulate(job['policy_id'], expected_revision=job['policy_revision'],
                                             actor='scheduler', selection=selected, persist=False), cursor

    def two_candidates(self):
        _, _, first, repo, policy, config = self.prepared()
        _, _, second, _, _, other_config = self.prepared(label='Y', key='other-policy')
        updated_config = replace(config, source_ids=config.source_ids + other_config.source_ids)
        policy = repo.update(policy['policy_id'], updated_config,
                              expected_revision=1, expected_state_revision=1, actor='human', reason='Both sources')
        return first, second, self.authorize(repo, policy)

    def test_alternating_unchanged_pages_reuse_durable_simulations(self):
        first, second, _ = self.two_candidates()
        for candidate in (first, second):
            self.runtime.semantic_repository.set_manual_lock(candidate.target_claim_id, True)
        scheduler = self.runtime.automation_scheduler
        with patch.object(scheduler.repository, 'page_size', 1):
            for _ in range(6):
                self.due()
                scheduler.tick()
        self.assertEqual(self.counts(), (2, 0, 0))

    def test_large_batch_is_split_and_cursor_preserves_remaining_proposals(self):
        first, second, policy = self.two_candidates()
        scheduler = self.runtime.automation_scheduler
        simulate = scheduler.simulation.simulate
        def limited(*args, **kwargs):
            if len(kwargs['selection']) > 1:
                raise AutomationPlanTooLarge()
            return simulate(*args, **kwargs)
        with patch.object(scheduler.simulation, 'simulate', side_effect=limited):
            scheduler.tick()
        self.assertEqual(self.schedule(policy)['candidate_cursor'], first.candidate_id)
        scheduler.tick()
        self.due()
        scheduler.tick()
        scheduler.tick()
        self.assertEqual(self.counts(), (2, 2, 2))
        self.assertEqual(self.runtime.semantic_repository.get_candidate(second.candidate_id).status, 'APPLIED')

    def test_oversized_single_preview_is_audited_and_next_candidate_can_progress(self):
        first, second, policy = self.two_candidates()
        scheduler = self.runtime.automation_scheduler
        preview = self.runtime.semantic_maintenance.preview_application
        def oversized(candidate_id, **kwargs):
            item = preview(candidate_id, **kwargs)
            if candidate_id == first.candidate_id:
                item['oversized_fixture'] = 'x' * (8 * 1024 * 1024)
            return item
        with patch.object(self.runtime.semantic_maintenance, 'preview_application', side_effect=oversized):
            scheduler.tick()
        status = self.schedule(policy)
        self.assertEqual(status['error_code'], 'PLAN_TOO_LARGE')
        self.assertEqual(status['candidate_cursor'], first.candidate_id)
        self.assertEqual(self.counts(), (0, 0, 0))
        self.due()
        scheduler.tick()
        scheduler.tick()
        self.assertEqual(self.runtime.semantic_repository.get_candidate(first.candidate_id).status, 'PENDING_REVIEW')
        self.assertEqual(self.runtime.semantic_repository.get_candidate(second.candidate_id).status, 'APPLIED')
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            event = connection.execute("SELECT details_json FROM events WHERE event_type='AUTOMATION_SCHEDULE_FAILED'")
            self.assertIn('oversized_candidate', event.fetchone()[0])

    def test_defaults_never_evaluate_or_publish(self):
        old, _, _, repo, policy, _ = self.prepared()
        before = old.vault_path.read_bytes()
        scheduler = self.runtime.automation_scheduler
        with patch.object(scheduler.simulation, 'simulate', side_effect=AssertionError('must not evaluate')):
            self.assertFalse(scheduler.tick())
            repo.set_paused(False, expected_revision=1, actor='human', reason='Test only')
            self.assertFalse(scheduler.tick())  # Disabled policy remains excluded after global resume.
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertEqual(before, old.vault_path.read_bytes())

    def test_authorized_pipeline_schedules_and_publishes_without_broker(self):
        old, _, candidate, repo, policy, _ = self.prepared()
        before = old.vault_path.read_bytes()
        policy = self.authorize(repo, policy)
        scheduler = self.runtime.automation_scheduler
        self.assertTrue(scheduler.tick())
        self.assertEqual(self.counts(), (1, 1, 0))
        self.assertEqual(before, old.vault_path.read_bytes())
        self.assertTrue(scheduler.tick())
        applied = self.runtime.semantic_repository.get_candidate(candidate.candidate_id)
        self.assertEqual(applied.status, 'APPLIED')
        self.assertEqual(applied.automation_run_id, self.schedule(policy)['last_run_id'])
        self.assertEqual(self.counts(), (1, 1, 1))
        self.assertFalse(scheduler.tick())
        self.assertFalse(self.runtime.broker_worker.running)

    def test_unchanged_blocked_plan_is_not_recreated_after_restart(self):
        _, _, candidate, repo, policy, _ = self.prepared()
        policy = self.authorize(repo, policy)
        self.runtime.semantic_repository.set_manual_lock(candidate.target_claim_id, True)
        scheduler = self.runtime.automation_scheduler
        scheduler.tick()
        self.assertEqual(self.counts(), (1, 0, 0))
        initial = self.schedule(policy)['last_simulation_id']
        scheduler = AutomationScheduler(AutomationScheduleRepository(self.runtime.database),
                                       scheduler.simulation, scheduler.execution)
        self.assertFalse(scheduler.tick())
        self.due()
        self.assertTrue(scheduler.tick())
        self.assertEqual(self.counts(), (1, 0, 0))
        self.assertEqual(self.schedule(policy)['last_simulation_id'], initial)
        self.runtime.semantic_repository.set_manual_lock(candidate.target_claim_id, False)
        self.due()
        scheduler.tick()
        scheduler.tick()
        self.assertEqual(self.counts(), (2, 1, 1))

    def test_simulation_run_and_cursor_are_committed_together(self):
        _, _, _, repo, policy, _ = self.prepared()
        policy = self.authorize(repo, policy)
        schedules = self.runtime.automation_scheduler.repository
        job = schedules.lease_due()
        preview, cursor = self.preview(job)
        with self.runtime.database.transaction() as connection:
            connection.execute('CREATE TRIGGER simulate_schedule_commit_failure BEFORE UPDATE OF last_fingerprint '
                               "ON automation_schedules BEGIN SELECT RAISE(ABORT,'simulated failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            schedules.finish(job, preview, cursor)
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertEqual(self.schedule(policy)['candidate_cursor'], 0)
        with self.runtime.database.transaction() as connection:
            connection.execute('DROP TRIGGER simulate_schedule_commit_failure')
        run_id = schedules.finish(job, preview, cursor)
        self.assertEqual(self.counts(), (1, 1, 0))
        self.assertEqual(self.schedule(policy)['last_run_id'], run_id)
        with self.assertRaises(AutomationDenied):
            schedules.finish(job, preview, cursor)
        self.assertEqual(self.counts(), (1, 1, 0))

    def test_expired_lease_cannot_queue_or_overwrite_replacement(self):
        _, _, _, repo, policy, _ = self.prepared()
        policy = self.authorize(repo, policy)
        schedules = self.runtime.automation_scheduler.repository
        first = schedules.lease_due()
        preview, cursor = self.preview(first)
        self.assertIsNone(schedules.lease_due())
        with self.runtime.database.transaction() as connection:
            connection.execute('UPDATE automation_schedules SET lease_until=0')
        replacement = schedules.lease_due()
        with self.assertRaises(AutomationDenied):
            schedules.finish(first, preview, cursor)
        schedules.failed(first, 'EVALUATION_FAILED')
        self.assertEqual(self.schedule(policy)['lease_token'], replacement['lease_token'])
        schedules.finish(replacement, preview, cursor)
        self.assertEqual(self.counts(), (1, 1, 0))

    def test_pause_during_preview_prevents_queue(self):
        old, _, _, repo, policy, _ = self.prepared()
        before = old.vault_path.read_bytes()
        self.authorize(repo, policy)
        schedules = self.runtime.automation_scheduler.repository
        job = schedules.lease_due()
        preview, cursor = self.preview(job)
        repo.set_paused(True, expected_revision=repo.control()['revision'], actor='human', reason='Stop now')
        with self.assertRaises(AutomationDenied):
            schedules.finish(job, preview, cursor)
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertEqual(before, old.vault_path.read_bytes())

    def test_reauthorized_edit_invalidates_previous_schedule(self):
        _, _, _, repo, policy, config = self.prepared()
        policy = self.authorize(repo, policy)
        schedules = self.runtime.automation_scheduler.repository
        job = schedules.lease_due()
        preview, cursor = self.preview(job)
        updated = repo.update(policy['policy_id'], replace(config, name='Revised'),
                              expected_revision=policy['revision'], expected_state_revision=policy['state_revision'],
                              actor='human', reason='New version')
        self.authorize(repo, updated)
        with self.assertRaises(AutomationDenied):
            schedules.finish(job, preview, cursor)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_concurrent_schedulers_lease_policy_once(self):
        _, _, _, repo, policy, _ = self.prepared()
        self.authorize(repo, policy)
        schedules = self.runtime.automation_scheduler.repository
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = list(pool.map(lambda _: schedules.lease_due(), range(2)))
        self.assertEqual(sum(job is not None for job in jobs), 1)

    def test_pending_run_prevents_new_evaluation_for_same_policy(self):
        _, _, _, repo, policy, _ = self.prepared()
        self.authorize(repo, policy)
        scheduler = self.runtime.automation_scheduler
        scheduler.tick()
        self.due()
        self.assertIsNone(scheduler.repository.lease_due())
        run = scheduler.execution.repository.claim_next()
        scheduler.execution.repository.pause_for_recovery(run['run_id'])
        self.assertIsNone(scheduler.repository.lease_due())
        self.assertEqual(self.counts(), (1, 1, 0))

    def test_error_backoff_does_not_starve_other_policy_or_leak_content(self):
        _, _, _, repo, first, _ = self.prepared()
        self.authorize(repo, first)
        _, _, _, repo, second, _ = self.prepared(label='Y', key='policy-two')
        self.authorize(repo, second)
        scheduler = self.runtime.automation_scheduler
        with patch.object(scheduler.simulation, 'simulate', side_effect=ValueError('private input content')):
            scheduler.tick()
        failed = self.schedule(first)
        self.assertEqual(failed['error_code'], 'EVALUATION_FAILED')
        self.assertGreater(failed['next_check_at'], failed['last_checked_at'])
        scheduler.tick()
        self.assertIsNotNone(self.schedule(second)['last_run_id'])
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            events = str([tuple(row) for row in connection.execute('SELECT * FROM events')])
        self.assertNotIn('private input content', events)

    def test_worker_start_stop_and_visible_status(self):
        _, _, _, repo, policy, _ = self.prepared()
        self.authorize(repo, policy)
        worker = self.runtime.automation_worker
        entered, release = threading.Event(), threading.Event()
        def tick():
            entered.set()
            release.wait(2)
        with patch.object(worker.scheduler, 'tick', side_effect=tick):
            try:
                worker.start()
                self.assertTrue(entered.wait(2))
                worker.start()
                status = OperationsStatusService(self.runtime).snapshot()
                self.assertTrue(status['workers']['automations'])
                self.assertTrue(status['autoapproval']['enabled'])
                repo.set_paused(True, expected_revision=repo.control()['revision'], actor='human', reason='Pause')
                self.assertFalse(OperationsStatusService(self.runtime).snapshot()['autoapproval']['enabled'])
            finally:
                release.set()
                worker.stop()
        self.assertFalse(worker.running)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_selection_pages_beyond_one_thousand_and_filters_source_and_status(self):
        _, new, candidate, repo, policy, _ = self.prepared()
        self.authorize(repo, policy)
        # Seed independent candidate identities to exercise real SQL pagination, not publication.
        with self.runtime.database.transaction() as connection:
            for index in range(1001):
                claim_id = connection.execute(
                    'INSERT INTO knowledge_claims(note_id,source_capture_id,statement,normalized_statement,'
                    'claim_type,volatility,span_start,span_end) VALUES (?,?,?,?,?,?,?,?)',
                    (new.note_id, new.capture_id, f'Claim {index}', f'claim {index}', 'VERSION', 'HIGH', 0, 1)
                ).lastrowid
                connection.execute('INSERT INTO update_candidates(target_note_id,target_claim_id,new_claim_id,'
                                   'retrieval_reason,status) VALUES (?,?,?,?,?)',
                                   (candidate.target_note_id, candidate.target_claim_id, claim_id,
                                    'pagination fixture', 'PENDING_REVIEW' if index < 1000 else 'REJECTED'))
        _, _, outside, _, _, _ = self.prepared(label='Outside', key='outside-policy')
        schedules = self.runtime.automation_scheduler.repository
        job = schedules.lease_due()
        first, cursor = schedules.selection(job)
        second, final_cursor = schedules.selection({**job, 'candidate_cursor': cursor})
        wrapped, _ = schedules.selection({**job, 'candidate_cursor': final_cursor})
        self.assertEqual((len(first), len(second)), (1000, 1))
        self.assertEqual(first, wrapped)
        self.assertGreater(final_cursor, cursor)
        self.assertNotIn(outside.candidate_id, [item['candidate_id'] for item in first + second])
        self.assertEqual(len({item['candidate_id'] for item in first + second}), 1001)
