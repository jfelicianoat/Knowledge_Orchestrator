from __future__ import annotations

import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from unittest.mock import patch

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict, KnowledgeState
from knowledge_orchestrator.services.maintenance_reversion import MaintenanceReversionService
from tests import test_automation_execution as execution
from tests import test_automation_governance as governance
from tests import test_phase_six_semantic_maintenance as phase_six
from tests import test_phase_twelve_knowledge_maintenance as phase_twelve


class Interrupted(BaseException):
    pass


class MaintenanceReversionTests(unittest.TestCase):
    setUp = governance.AutomationGovernanceTests.setUp
    tearDown = governance.AutomationGovernanceTests.tearDown
    publish_monitored = governance.AutomationGovernanceTests.publish_monitored
    extraction = staticmethod(governance.AutomationGovernanceTests.extraction)
    prepared = governance.AutomationGovernanceTests.prepared
    simulation = governance.AutomationGovernanceTests.simulation
    authorize = execution.AutomationExecutionTests.authorize
    queue = execution.AutomationExecutionTests.queue
    publish = phase_six.PhaseSixSemanticMaintenanceTests.publish
    decision = staticmethod(phase_twelve.PhaseTwelveKnowledgeMaintenanceTests.decision)

    def applied(self, **kwargs):
        old, new, candidate, repo, policy, _ = self.prepared(**kwargs)
        before = old.vault_path.read_text(encoding='utf-8')
        run = self.queue(repo, self.authorize(repo, policy), candidate)
        self.runtime.automation_execution.run_next()
        candidate = self.runtime.semantic_repository.get_candidate(candidate.candidate_id)
        self.assertEqual(candidate.status, 'APPLIED')
        return old, new, candidate, before, run

    def preview(self, candidate, key='preview-revert-001'):
        return self.runtime.maintenance_reversion.preview(candidate.candidate_id,
            expected_revision=candidate.proposal_revision, actor='human:owner', key=key)

    def confirm(self, plan, service=None, **kwargs):
        return (service or self.runtime.maintenance_reversion).confirm(plan['reversion_id'], **{
            'actor': 'human:owner', 'expected_plan_hash': plan['plan_hash'], 'reason': 'Restaurar tras revisión humana',
            **kwargs})

    def test_reversion_restores_note_and_vigency_with_immutable_history_and_policy_receipt(self):
        old, _, candidate, before, run = self.applied()
        published = old.vault_path.read_text(encoding='utf-8')
        original_history = self.runtime.knowledge.repository.history(candidate.target_claim_id)
        plan = self.preview(candidate)
        self.assertEqual(plan['status'], 'PREVIEW')
        self.assertFalse(plan['plan']['publication_authorized'])
        self.assertEqual(old.vault_path.read_text(encoding='utf-8'), published)
        self.assertEqual(plan['plan']['proposed'], before)
        self.assertEqual(self.confirm(plan)['status'], 'APPLIED')
        self.assertEqual(old.vault_path.read_text(encoding='utf-8'), before)
        target = self.runtime.semantic_repository.get_claim(candidate.target_claim_id)
        successor = self.runtime.semantic_repository.get_claim(candidate.applied_successor_id)
        self.assertEqual((target.status, target.knowledge_state, target.superseded_by), ('ACTIVE', 'CURRENT', None))
        self.assertEqual((successor.status, successor.knowledge_state, successor.superseded_by),
                         ('RETRACTED', 'HISTORICAL', target.claim_id))
        history = self.runtime.knowledge.repository.history(target.claim_id)
        self.assertEqual(history[:len(original_history)], original_history)
        self.assertEqual([row['to_state'] for row in history], ['CURRENT', 'SUPERSEDED', 'CURRENT'])
        current = self.runtime.knowledge.repository.claims(note_id=old.note_id)
        self.assertEqual([claim.claim_id for claim in current], [target.claim_id])
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate.candidate_id).status, 'APPLIED')
        self.assertEqual(self.runtime.automation_execution.repository.get(run['run_id'])['results'], {'APPLIED': 1})
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            versions = connection.execute('SELECT content_text FROM note_revisions WHERE note_id=? ORDER BY revision',
                                           (old.note_id,)).fetchall()
            self.assertEqual([row[0] for row in versions], [before, published])
            self.assertEqual(connection.execute('SELECT count(*) FROM automation_reservations').fetchone()[0], 1)
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_plan_is_idempotent_frozen_and_owner_scoped_and_cannot_be_tampered(self):
        old, _, candidate, _, _ = self.applied()
        plan = self.preview(candidate)
        old.vault_path.write_text('Cambió fuera de la aplicación', encoding='utf-8')
        self.assertEqual(self.preview(candidate), plan)
        with self.assertRaises(ValueError):
            self.runtime.maintenance_reversion.repository.get(plan['reversion_id'], actor='other')
        for statement in ('UPDATE maintenance_reversions SET plan_json=\'{}\'',
                          'DELETE FROM maintenance_reversions', 'DELETE FROM maintenance_reversion_notes'):
            with self.subTest(statement=statement), closing(self.runtime.database.connect()) as connection:
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(statement)

    def test_external_note_change_after_preview_and_manual_lock_prevent_publication(self):
        old, _, candidate, _, _ = self.applied()
        plan = self.preview(candidate)
        published = old.vault_path.read_text(encoding='utf-8')
        old.vault_path.write_text(published + '\nEdición humana', encoding='utf-8')
        with self.assertRaises(KnowledgeConflict):
            self.confirm(plan)
        old.vault_path.write_bytes(published.encode('utf-8'))
        self.runtime.semantic_repository.set_manual_lock(candidate.applied_successor_id, True)
        with self.assertRaisesRegex(KnowledgeConflict, 'MANUAL_LOCK'):
            self.confirm(plan)
        self.assertEqual(old.vault_path.read_text(encoding='utf-8'), published)
        self.assertEqual(self.preview(candidate)['status'], 'PREVIEW')

    def test_unreviewed_hash_wrong_actor_and_empty_reason_cannot_confirm(self):
        old, _, candidate, _, _ = self.applied()
        plan, published = self.preview(candidate), old.vault_path.read_bytes()
        for fields in ({'expected_plan_hash': 'wrong'}, {'actor': 'other'}, {'reason': ''}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.confirm(plan, **fields)
        self.assertEqual(old.vault_path.read_bytes(), published)

    def test_subsequent_claim_decision_blocks_reversion_even_if_state_returns_to_current(self):
        _, _, candidate, _, _ = self.applied()
        repo = self.runtime.knowledge.repository
        repo.review_state(candidate.applied_successor_id, KnowledgeState.UNCERTAIN, expected_revision=1,
                          actor='human:owner', reason='Revisar evidencia')
        repo.review_state(candidate.applied_successor_id, KnowledgeState.CURRENT, expected_revision=2,
                          actor='human:owner', reason='Revisión posterior')
        with self.assertRaisesRegex(KnowledgeConflict, 'decisiones posteriores'):
            self.preview(candidate)

    def test_crashes_before_and_after_replace_recover_without_duplicate_history(self):
        for checkpoint in ('reversion_intent', 'reversion_note_replaced'):
            with self.subTest(checkpoint=checkpoint):
                old, _, candidate, before, _ = self.applied(label=checkpoint, key=f'policy-{checkpoint}')
                plan = self.preview(candidate, key=f'preview-{checkpoint}')
                def interrupt(name, checkpoint=checkpoint):
                    if name == checkpoint:
                        raise Interrupted()
                service = MaintenanceReversionService(self.runtime.maintenance_reversion.repository,
                    self.runtime.semantic_maintenance, checkpoint=interrupt)
                with self.assertRaises(Interrupted):
                    self.confirm(plan, service)
                self.assertEqual(self.runtime.maintenance_reversion.repository.get(plan['reversion_id'],
                                 actor='human:owner')['status'], 'APPLYING')
                self.assertEqual(self.runtime.knowledge.repository.claims(note_id=old.note_id), [])
                self.runtime.maintenance_reversion.recover()
                self.runtime.maintenance_reversion.recover()
                self.assertEqual(old.vault_path.read_text(encoding='utf-8'), before)
                self.assertEqual(self.confirm(plan)['status'], 'APPLIED')
                self.assertEqual(len(self.runtime.knowledge.repository.history(candidate.target_claim_id)), 3)

    def test_reserved_notes_block_locks_state_review_and_extraction_until_recovery(self):
        old, _, candidate, _, _ = self.applied()
        plan = self.preview(candidate)
        def interrupt(_name):
            raise Interrupted()
        service = MaintenanceReversionService(self.runtime.maintenance_reversion.repository,
            self.runtime.semantic_maintenance, checkpoint=interrupt)
        with self.assertRaises(Interrupted):
            self.confirm(plan, service)
        with self.assertRaises(ValueError):
            self.runtime.semantic_repository.set_manual_lock(candidate.applied_successor_id, True)
        with self.assertRaises(KnowledgeConflict):
            self.runtime.knowledge.repository.review_state(candidate.applied_successor_id, KnowledgeState.UNCERTAIN,
                expected_revision=1, actor='human:owner', reason='Cambio durante reversión')
        with self.assertRaises(ValueError):
            self.runtime.semantic_maintenance.ingest_extraction(old.note_id,
                self.extraction(old, 'Producto X versión 2.'))
        self.runtime.maintenance_reversion.recover()

    def test_concurrent_confirmation_applies_once_and_retains_exact_receipt(self):
        old, _, candidate, before, _ = self.applied()
        plan = self.preview(candidate)
        def confirm():
            try:
                return self.confirm(plan)['status']
            except KnowledgeConflict:
                return 'CONCURRENT'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: confirm(), range(2)))
        self.assertIn('APPLIED', results)
        self.assertTrue(set(results) <= {'APPLIED', 'CONCURRENT'})
        self.assertEqual(old.vault_path.read_text(encoding='utf-8'), before)
        self.assertEqual(len(self.runtime.knowledge.repository.history(candidate.target_claim_id)), 3)
        with self.assertRaises(KnowledgeConflict):
            self.preview(candidate, key='second-reversion')

    def test_sqlite_failure_after_replace_keeps_intent_for_recovery(self):
        old, _, candidate, before, _ = self.applied()
        plan = self.preview(candidate)
        repo = self.runtime.maintenance_reversion.repository
        with patch.object(repo, 'finish', side_effect=sqlite3.OperationalError('interrupted commit')):
            with self.assertRaises(sqlite3.OperationalError):
                self.confirm(plan)
        self.assertEqual(old.vault_path.read_text(encoding='utf-8'), before)
        self.assertEqual(repo.get(plan['reversion_id'], actor='human:owner')['status'], 'APPLYING')
        self.runtime.maintenance_reversion.recover()
        self.assertEqual(repo.get(plan['reversion_id'], actor='human:owner')['status'], 'APPLIED')

    def test_conflict_after_intent_keeps_external_edit_and_excludes_current_until_reconciled(self):
        old, _, candidate, _, _ = self.applied()
        plan = self.preview(candidate)
        external = 'Cambio externo durante la confirmación'
        def modify(name):
            if name == 'reversion_intent':
                old.vault_path.write_text(external, encoding='utf-8')
        service = MaintenanceReversionService(self.runtime.maintenance_reversion.repository,
            self.runtime.semantic_maintenance, checkpoint=modify)
        with self.assertRaises(KnowledgeConflict):
            self.confirm(plan, service)
        self.assertEqual(old.vault_path.read_text(encoding='utf-8'), external)
        receipt = service.repository.get(plan['reversion_id'], actor='human:owner')
        self.assertEqual(receipt['status'], 'CONFLICT')
        self.assertEqual(self.runtime.knowledge.repository.claims(note_id=old.note_id), [])
        service.recover()
        self.assertEqual(service.repository.get(plan['reversion_id'], actor='human:owner'), receipt)

    def test_complex_snapshot_reversion_preserves_unaffected_claim_and_offsets(self):
        old_text, new_text = 'Producto X versión 1.', 'Producto X versión 200 ampliada.'
        untouched = 'Soporte sin cambios.'
        old = self.publish('revert_complex_old', f'# Documento\n\n{old_text}\n\n{untouched}\n')
        new = self.publish('revert_complex_new', '# Documento\n\n' + new_text + '\n')
        service, repo = self.runtime.semantic_maintenance, self.runtime.semantic_repository
        payload = self.extraction(old, old_text)
        payload['claims'] += self.extraction(old, untouched, entities=('Soporte',))['claims']
        service.ingest_extraction(old.note_id, payload)
        unaffected = repo.list_claims(old.note_id)[1]
        candidates = service.ingest_extraction(new.note_id, self.extraction(new, new_text))
        candidate = next(repo.get_candidate(identifier) for identifier in candidates
                         if repo.get_candidate(identifier).target_claim_id != unaffected.claim_id)
        before = old.vault_path.read_text(encoding='utf-8')
        service.compare(candidate.candidate_id, self.decision(new_text))
        candidate = service.approve(candidate.candidate_id)
        self.assertNotEqual(repo.get_claim(unaffected.claim_id).span_start, unaffected.span_start)
        plan = self.preview(candidate)
        self.confirm(plan)
        restored = repo.get_claim(unaffected.claim_id)
        self.assertEqual((restored.span_start, restored.span_end), (unaffected.span_start, unaffected.span_end))
        self.assertEqual(restored.knowledge_state, 'CURRENT')
        self.assertEqual(old.vault_path.read_text(encoding='utf-8'), before)
        self.assertEqual(before[restored.span_start:restored.span_end], untouched)

    def _dependent(self, candidate):
        other = self.publish('dependent_note', '# Otra nota\n\nProducto X versión 0.\n')
        service, repo = self.runtime.semantic_maintenance, self.runtime.semantic_repository
        service.ingest_extraction(other.note_id, self.extraction(other, 'Producto X versión 0.'))
        target = repo.list_claims(other.note_id)[0]
        successor = repo.get_claim(candidate.applied_successor_id)
        dependency = repo.create_candidate(target, successor, retrieval_reason='reuse existing evidence')
        return service.compare(dependency.candidate_id, self.decision(successor.statement))

    def test_published_dependency_blocks_rollback_without_changing_either_note(self):
        old, _, candidate, _, _ = self.applied()
        dependency = self._dependent(candidate)
        self.runtime.semantic_maintenance.approve(dependency.candidate_id)
        published = old.vault_path.read_bytes()
        with self.assertRaisesRegex(KnowledgeConflict, 'derivado'):
            self.preview(candidate)
        self.assertEqual(old.vault_path.read_bytes(), published)

    def test_dependency_application_and_reversion_reserve_each_other(self):
        _, _, candidate, _, _ = self.applied()
        dependency = self._dependent(candidate)
        plan = self.preview(candidate)
        def interrupt(_name):
            raise Interrupted()
        service = MaintenanceReversionService(self.runtime.maintenance_reversion.repository,
            self.runtime.semantic_maintenance, checkpoint=interrupt)
        with self.assertRaises(Interrupted):
            self.confirm(plan, service)
        with self.assertRaises(KnowledgeConflict):
            self.runtime.semantic_maintenance.approve(dependency.candidate_id)
        self.runtime.maintenance_reversion.recover()

    def test_latest_publication_only_and_damaged_revision_cannot_be_restored(self):
        old, _, first, _, _ = self.applied()
        service, repo = self.runtime.semantic_maintenance, self.runtime.semantic_repository
        next_text = 'Producto X versión 3.'
        new = self.publish('latest_new', '# Nueva versión\n\n' + next_text + '\n')
        ids = service.ingest_extraction(new.note_id, self.extraction(new, next_text))
        second = next(repo.get_candidate(identifier) for identifier in ids
                      if repo.get_candidate(identifier).target_claim_id == first.applied_successor_id)
        service.compare(second.candidate_id, self.decision(next_text))
        second = service.approve(second.candidate_id)
        published = old.vault_path.read_bytes()
        with self.assertRaises(KnowledgeConflict):
            self.preview(first)
        with self.runtime.database.transaction(immediate=True) as connection:
            connection.execute("UPDATE note_revisions SET content_text='damaged' WHERE candidate_id=?",
                               (second.candidate_id,))
        with self.assertRaisesRegex(KnowledgeConflict, 'verificable'):
            self.preview(second, key='damaged-snapshot')
        self.assertEqual(old.vault_path.read_bytes(), published)

    def test_reversing_second_update_restores_projection_and_checks_its_original_source(self):
        old, witness, first, _, _ = self.applied()
        previous = old.vault_path.read_bytes()
        service, repo = self.runtime.semantic_maintenance, self.runtime.semantic_repository
        next_text = 'Producto X versión 3.'
        new = self.publish('third_version', '# Nueva versión\n\n' + next_text + '\n')
        ids = service.ingest_extraction(new.note_id, self.extraction(new, next_text))
        second = next(repo.get_candidate(identifier) for identifier in ids
                      if repo.get_candidate(identifier).target_claim_id == first.applied_successor_id)
        service.compare(second.candidate_id, self.decision(next_text))
        second = service.approve(second.candidate_id)
        plan = self.preview(second)
        witness_bytes = witness.vault_path.read_bytes()
        witness.vault_path.write_bytes(witness_bytes.replace(b'\n', b'\r\n'))
        with self.assertRaises(KnowledgeConflict):
            self.confirm(plan)
        witness.vault_path.write_bytes(witness_bytes)
        self.confirm(plan)
        self.assertEqual(old.vault_path.read_bytes(), previous)
        restored = repo.get_claim(first.applied_successor_id)
        self.assertEqual(restored.knowledge_state, 'CURRENT')
        self.assertEqual(restored.derived_from_claim_id, first.new_claim_id)
        self.assertEqual({c.claim_id for c in self.runtime.knowledge.repository.succession(restored.claim_id)},
                         {first.target_claim_id, first.applied_successor_id, second.applied_successor_id})

    def test_pending_dependent_publication_blocks_reversion_plan(self):
        _, _, candidate, _, _ = self.applied()
        dependency = self._dependent(candidate)
        from knowledge_orchestrator.services.semantic_maintenance import SemanticMaintenanceService
        def interrupt(name):
            if name == 'semantic_intent':
                raise Interrupted()
        service = SemanticMaintenanceService(self.runtime.semantic_repository, checkpoint=interrupt)
        with self.assertRaises(Interrupted):
            service.approve(dependency.candidate_id)
        with self.assertRaisesRegex(KnowledgeConflict, 'pendiente'):
            self.preview(candidate)
        self.runtime.semantic_maintenance.recover()

    def test_failed_confirmation_transaction_does_not_leave_snapshot_or_reservation(self):
        _, _, candidate, _, _ = self.applied()
        plan = self.preview(candidate)
        with self.runtime.database.transaction(immediate=True) as connection:
            connection.execute("CREATE TRIGGER simulate_confirm_failure BEFORE UPDATE ON maintenance_reversions "
                               "WHEN NEW.status='APPLYING' BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.confirm(plan)
        self.assertEqual(self.runtime.maintenance_reversion.repository.pending(), [])
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM note_revisions WHERE reason LIKE ?',
                                                ('REVERSION:%',)).fetchone()[0], 0)

    def test_runtime_recovery_finishes_reversion_before_reconciliation(self):
        old, _, candidate, before, _ = self.applied()
        plan = self.preview(candidate)
        def interrupt(name):
            if name == 'reversion_intent':
                raise Interrupted()
        service = MaintenanceReversionService(self.runtime.maintenance_reversion.repository,
            self.runtime.semantic_maintenance, checkpoint=interrupt)
        with self.assertRaises(Interrupted):
            self.confirm(plan, service)
        self.runtime.recover_once(ingest_inbox=False)
        self.assertEqual(old.vault_path.read_text(encoding='utf-8'), before)
        self.assertEqual(self.runtime.maintenance_reversion.repository.get(plan['reversion_id'],
                         actor='human:owner')['status'], 'APPLIED')
        self.assertIn(candidate.target_claim_id,
                      [claim.claim_id for claim in self.runtime.knowledge.repository.claims(note_id=old.note_id)])

    def test_repeated_unchanged_quotes_shift_without_transient_unique_collision(self):
        old_text, new_text, quote = 'Producto X versión 12345678901234567890.', 'Producto X v2.', 'Soporte.'
        gap = len(old_text) - len(new_text)
        body = f'# Documento\n\n{old_text}\n\n{quote}' + ' ' * (gap - len(quote)) + quote + '\n'
        old = self.publish('repeated_old', body)
        new = self.publish('repeated_new', '# Documento\n\n' + new_text + '\n')
        service, repo = self.runtime.semantic_maintenance, self.runtime.semantic_repository
        payload = self.extraction(old, old_text)
        support = self.extraction(old, quote, entities=('Soporte',))['claims'][0]
        payload['claims'] += [support, {**support, 'span_start': support['span_start'] + gap,
                                        'span_end': support['span_end'] + gap}]
        service.ingest_extraction(old.note_id, payload)
        others = repo.list_claims(old.note_id)[1:]
        ids = service.ingest_extraction(new.note_id, self.extraction(new, new_text))
        candidate = next(repo.get_candidate(identifier) for identifier in ids
                         if repo.get_candidate(identifier).target_claim_id == repo.list_claims(old.note_id)[0].claim_id)
        service.compare(candidate.candidate_id, self.decision(new_text))
        candidate = service.approve(candidate.candidate_id)
        self.confirm(self.preview(candidate))
        for claim in others:
            restored = repo.get_claim(claim.claim_id)
            self.assertEqual((restored.span_start, restored.span_end), (claim.span_start, claim.span_end))
            self.assertEqual(old.vault_path.read_text(encoding='utf-8')[restored.span_start:restored.span_end], quote)
