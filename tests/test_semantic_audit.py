from __future__ import annotations

import json
import sqlite3
import unittest
from contextlib import closing

from tests import test_automation_execution as execution
from tests import test_automation_governance as governance
from tests import test_phase_six_semantic_maintenance as phase_six


class SemanticAuditTests(unittest.TestCase):
    setUp = phase_six.PhaseSixSemanticMaintenanceTests.setUp
    tearDown = phase_six.PhaseSixSemanticMaintenanceTests.tearDown
    publish = phase_six.PhaseSixSemanticMaintenanceTests.publish
    extraction = staticmethod(phase_six.PhaseSixSemanticMaintenanceTests.extraction)
    prepare_candidate = phase_six.PhaseSixSemanticMaintenanceTests.prepare_candidate
    publish_monitored = governance.AutomationGovernanceTests.publish_monitored
    prepared = governance.AutomationGovernanceTests.prepared
    authorize = execution.AutomationExecutionTests.authorize
    simulation = governance.AutomationGovernanceTests.simulation
    queue = execution.AutomationExecutionTests.queue

    def events(self, kind, **match):
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            rows = connection.execute('SELECT * FROM events WHERE event_type=? ORDER BY event_id', (kind,)).fetchall()
        values = [{**json.loads(row['details_json']), 'event_created_at': row['created_at']} for row in rows]
        return [value for value in values if all(value.get(key) == expected for key, expected in match.items())]

    def job(self, name):
        note = self.publish(name, '# Documento\n\nContenido privado de prueba.\n')
        return self.runtime.semantic_repository.get_job(f'semantic_extract_note_{note.note_id}')

    def test_job_transitions_retry_and_recovery_are_durable_without_polling_duplicates_or_content(self):
        repo = self.runtime.semantic_repository
        job = self.job('audit_lifecycle')
        repo.create_job(job_id=job.job_id, kind='EXTRACT', idempotency_key=job.idempotency_key,
                        request={}, note_id=job.note_id)
        repo.claim_job(job.job_id)
        repo.retry_job(job.job_id, next_retry_at='2000-01-01', message='private-error-token')
        repo.claim_job(job.job_id)
        repo.recover_jobs()
        repo.recover_jobs()
        repo.claim_job(job.job_id)
        for _ in range(2):
            repo.accept_job(job.job_id, {'task_id': 'broker-audit-001', 'status_url': '/tasks/private-query'})
            repo.update_job_status(job.job_id, {'status': 'queued'})
        for _ in range(2):
            repo.update_job_status(job.job_id, {'status': 'processing'})
        repo.update_job_status(job.job_id, {'status': 'completed', 'result': {'result_markdown': 'private-result'}})
        repo.complete_job(job.job_id)
        repo.complete_job(job.job_id)
        repo.fail_job(job.job_id, 'private-error-code', 'private-error-token')
        events = self.events('SEMANTIC_JOB_STATE_CHANGED', job_id=job.job_id)
        self.assertEqual([event['status'] for event in events],
                         ['READY', 'SUBMITTING', 'READY', 'SUBMITTING', 'READY', 'SUBMITTING',
                          'QUEUED', 'PROCESSING', 'SUCCESS'])
        self.assertEqual([event['from_status'] for event in events], [None, *[e['status'] for e in events[:-1]]])
        self.assertEqual(events[-1]['broker_task_id'], 'broker-audit-001')
        self.assertEqual(events[-1]['attempt'], 3)
        self.assertEqual(events[-1]['action'], 'result_integrated')
        for secret in ('Contenido privado', 'private-error', 'private-result', 'private-query', 'request_json'):
            self.assertNotIn(secret, json.dumps(events))

    def test_terminal_failures_are_recorded_once_without_raw_remote_errors(self):
        repo = self.runtime.semantic_repository
        for remote in (False, True):
            job = self.job(f'audit_error_{remote}')
            if remote:
                repo.claim_job(job.job_id)
                repo.accept_job(job.job_id, {'task_id': 'broker-error', 'status_url': '/tasks/error'})
                repo.update_job_status(job.job_id, {'status': 'failed', 'error':
                    {'code': 'private-error-code', 'message': 'private-error-message'}})
            else:
                repo.fail_job(job.job_id, 'private-error-code', 'private-error-message')
            repo.fail_job(job.job_id, 'second-error', 'second-error')
            failures = self.events('SEMANTIC_JOB_STATE_CHANGED', job_id=job.job_id, status='ERROR')
            self.assertEqual(len(failures), 1)
            self.assertNotIn('private-error', json.dumps(failures))

    def test_failed_audit_insert_rolls_back_job_transition_and_attempt(self):
        repo = self.runtime.semantic_repository
        job = self.job('audit_atomic_job')
        with self.runtime.database.transaction() as connection:
            connection.execute("CREATE TRIGGER audit_test_failure BEFORE INSERT ON events "
                               "WHEN NEW.event_type='SEMANTIC_JOB_STATE_CHANGED' "
                               "BEGIN SELECT RAISE(ABORT,'audit storage unavailable'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            repo.claim_job(job.job_id)
        stored = repo.get_job(job.job_id)
        self.assertEqual((stored.status, stored.attempt), ('READY', 0))
        self.assertEqual(len(self.events('SEMANTIC_JOB_STATE_CHANGED', job_id=job.job_id)), 1)

    def test_candidate_creation_and_conflict_are_idempotent_and_guarded(self):
        _, _, candidate_id, _, _ = self.prepare_candidate()
        repo = self.runtime.semantic_repository
        candidate = repo.get_candidate(candidate_id)
        repo.create_candidate(repo.get_claim(candidate.target_claim_id), repo.get_claim(candidate.new_claim_id),
                              retrieval_reason='private-retrieval-content')
        repo.mark_candidate(candidate_id, 'ERROR', reason='private-error', expected_revision=99)
        repo.mark_candidate(candidate_id, 'CONFLICT', reason='NOTE_CHANGED_AFTER_DIFF', expected_revision=0)
        repo.mark_candidate(candidate_id, 'CONFLICT', reason='NOTE_CHANGED_AFTER_DIFF', expected_revision=0)
        events = self.events('MAINTENANCE_CANDIDATE_STATE_CHANGED', candidate_id=candidate_id)
        self.assertEqual([event['status'] for event in events], ['PENDING_COMPARISON', 'CONFLICT'])
        self.assertEqual(events[-1]['reason_code'], 'NOTE_CHANGED_AFTER_DIFF')
        self.assertNotIn('private-', json.dumps(events))
        self.assertEqual(events[0]['new_claim_id'], candidate.new_claim_id)

    def test_policy_application_event_links_exact_decision_and_preserved_revision(self):
        old, _, candidate, policies, policy, _ = self.prepared()
        original = old.vault_path.read_text(encoding='utf-8')
        run = self.queue(policies, self.authorize(policies, policy), candidate)
        self.assertTrue(self.runtime.automation_execution.run_next())
        self.runtime.semantic_maintenance.recover()
        repo = self.runtime.semantic_repository
        repo.mark_applied(candidate.candidate_id)
        applied = self.events('SEMANTIC_UPDATE_APPLIED', candidate_id=candidate.candidate_id)
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]['automation_run_id'], run['run_id'])
        self.assertEqual(applied[0]['proposal_revision'], 1)
        self.assertEqual(applied[0]['actor'], f"policy:{policy['policy_id']}:revision:1")
        self.assertIsNotNone(applied[0]['successor_id'])
        self.assertEqual(repo.revision_content(candidate.candidate_id), original)
        intent = self.events('MAINTENANCE_CANDIDATE_STATE_CHANGED',
                             candidate_id=candidate.candidate_id, status='APPLYING')
        self.assertEqual(len(intent), 1)
        self.assertEqual(intent[0]['automation_run_id'], run['run_id'])
        stored_run = self.runtime.automation_execution.repository.get(run['run_id'])
        plan = policies.simulation(stored_run['simulation_id'])
        self.assertEqual(plan['policy_id'], policy['policy_id'])
        self.assertEqual(plan['plan']['items'][0]['candidate_id'], candidate.candidate_id)

    def test_applying_a_successor_records_conflicts_of_other_proposals_once(self):
        _, _, candidate, _, _, _ = self.prepared()
        repo = self.runtime.semantic_repository
        quote = 'Producto X usa la versión 3.0.'
        note = self.publish('audit_other_successor', '# Versión\n\n' + quote + '\n')
        self.runtime.semantic_maintenance.ingest_extraction(note.note_id, self.extraction(note, quote))
        other = repo.create_candidate(repo.get_claim(candidate.target_claim_id), repo.list_claims(note.note_id)[0],
                                      retrieval_reason='entity')
        self.runtime.semantic_maintenance.approve(candidate.candidate_id, actor='human:audit')
        repo.mark_applied(candidate.candidate_id)
        conflicts = self.events('MAINTENANCE_CANDIDATE_STATE_CHANGED', candidate_id=other.candidate_id,
                                status='CONFLICT')
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]['reason_code'], 'TARGET_SUPERSEDED')
        self.assertEqual(conflicts[0]['from_status'], 'PENDING_COMPARISON')
        self.assertEqual(repo.get_candidate(other.candidate_id).status, 'CONFLICT')

    def test_audit_failure_rolls_back_publication_intent_and_preserves_note(self):
        old, _, candidate, _, _, _ = self.prepared()
        original = old.vault_path.read_bytes()
        with self.runtime.database.transaction() as connection:
            connection.execute("CREATE TRIGGER audit_test_failure BEFORE INSERT ON events "
                               "WHEN NEW.event_type='MAINTENANCE_CANDIDATE_STATE_CHANGED' "
                               "BEGIN SELECT RAISE(ABORT,'audit storage unavailable'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.runtime.semantic_maintenance.approve(candidate.candidate_id)
        self.assertEqual(old.vault_path.read_bytes(), original)
        stored = self.runtime.semantic_repository.get_candidate(candidate.candidate_id)
        self.assertEqual(stored.status, 'PENDING_REVIEW')
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM note_revisions WHERE candidate_id=?',
                                                (candidate.candidate_id,)).fetchone()[0], 0)
