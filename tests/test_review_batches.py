from __future__ import annotations

import sqlite3
import threading
import time
import tkinter as tk
import unittest
from contextlib import closing
from unittest.mock import patch

import httpx

from knowledge_orchestrator.api.application import KnowledgeApi
from knowledge_orchestrator.api.auth import ApiAuth
from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.repositories.review_batch_repository import ReviewBatchRepository
from knowledge_orchestrator.services.review_batches import ReviewBatchService
from knowledge_orchestrator.services.semantic_maintenance import SemanticMaintenanceService
from knowledge_orchestrator.ui.dashboard import OrchestratorDashboard
from knowledge_orchestrator.ui.review_batch_dialog import ReviewBatchDialog
from knowledge_orchestrator.worker.review_worker import ReviewWorker
from tests import test_phase_six_semantic_maintenance as phase_six


class ReviewBatchTests(unittest.TestCase):
    setUp = phase_six.PhaseSixSemanticMaintenanceTests.setUp
    tearDown = phase_six.PhaseSixSemanticMaintenanceTests.tearDown
    publish = phase_six.PhaseSixSemanticMaintenanceTests.publish
    extraction = staticmethod(phase_six.PhaseSixSemanticMaintenanceTests.extraction)

    def candidate(self, label='A'):
        entity = f'Producto {label}'
        old_text, new_text = f'{entity} versión 1.', f'{entity} versión 2.'
        old = self.publish(f'old_{label}', f'# Estado\n\n{old_text}\n')
        new = self.publish(f'new_{label}', f'# Novedad\n\n{new_text}\n')
        service = self.runtime.semantic_maintenance
        service.ingest_extraction(old.note_id, self.extraction(old, old_text, entities=(entity,)))
        ids = service.ingest_extraction(new.note_id, self.extraction(new, new_text, entities=(entity,)))
        self.assertEqual(len(ids), 1)
        candidate = service.compare(ids[0], {'relation': 'SUPERSEDES', 'confidence': 0.99, 'impact': 'HIGH',
                                            'rationale': 'Nueva versión explícita.', 'replacement_text': new_text})
        return old, new, candidate

    def batches(self, checkpoint=None):
        return ReviewBatchService(ReviewBatchRepository(self.runtime.database),
                                  self.runtime.semantic_maintenance, checkpoint=checkpoint)

    def preview(self, service, *candidates, key='preview-0001'):
        return service.preview(owner='human:test', key=key, selection=[
            {'candidate_id': c.candidate_id, 'expected_revision': c.proposal_revision} for c in candidates])

    def confirm(self, service, batch):
        return service.repository.confirm(batch['batch_id'], owner='human:test', plan_hash=batch['plan_hash'])

    def receipt(self, service, batch):
        return service.repository.get(batch['batch_id'], owner='human:test')

    def test_preview_is_frozen_idempotent_and_does_not_publish(self):
        old, _, candidate = self.candidate()
        before = old.vault_path.read_bytes()
        service = self.batches()
        batch = self.preview(service, candidate)
        self.assertEqual(batch['plan']['counts']['eligible_tasks'], 1)
        self.assertEqual(batch['plan']['items'][0]['assessment'],
                         self.runtime.semantic_repository.proposal_versions(candidate.candidate_id)[0]['snapshot'])
        self.assertFalse(service.run_next())
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate.candidate_id), candidate)
        with closing(self.runtime.database.connect()) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM note_revisions').fetchone()[0], 0)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE review_batches SET plan_json='{}'")
        self.assertEqual(self.preview(service, candidate)['batch_id'], batch['batch_id'])
        with self.assertRaises(KnowledgeConflict):
            service.preview(owner='human:test', key='preview-0001', selection=None)
        with self.assertRaises(KnowledgeConflict):
            service.repository.confirm(batch['batch_id'], owner='human:test', plan_hash='wrong')
        with self.assertRaises(LookupError):
            service.repository.get(batch['batch_id'], owner='another:user')

    def test_confirmed_selection_reports_partial_results_and_preserves_late_edit(self):
        old_a, _, a = self.candidate('A')
        old_b, new_b, b = self.candidate('B')
        before_b = old_b.vault_path.read_bytes()
        service = self.batches()
        batch = self.preview(service, a, b)
        self.assertEqual(batch['plan']['counts']['eligible_tasks'], 2)
        new_b.vault_path.write_text('Modificación posterior a la revisión', encoding='utf-8')
        self.confirm(service, batch)
        self.assertTrue(service.run_next())
        receipt = self.receipt(service, batch)
        self.assertEqual(receipt['status'], 'COMPLETE')
        self.assertEqual(receipt['results'], {'APPLIED': 1, 'CONFLICT': 1})
        self.assertEqual(old_b.vault_path.read_bytes(), before_b)
        self.assertIn('Producto A versión 2.', old_a.vault_path.read_text(encoding='utf-8'))
        self.confirm(service, batch)
        self.assertFalse(service.run_next())

    def test_all_snapshot_excludes_later_candidates_and_missing_selection_is_skipped(self):
        self.candidate('A')
        service = self.batches()
        batch = service.preview(owner='human:test', key='all-0000001')
        _, _, b = self.candidate('B')
        self.assertEqual(service.preview(owner='human:test', key='all-0000001')['plan'], batch['plan'])
        self.confirm(service, batch)
        service.run_next()
        self.assertEqual(self.runtime.semantic_repository.get_candidate(b.candidate_id).status, 'PENDING_REVIEW')
        missing = service.preview(owner='human:test', key='missing-001', selection=[
            {'candidate_id': 999999, 'expected_revision': 0}])
        self.assertEqual(missing['results'], {'SKIPPED': 1})

    def test_crash_recovery_before_application_and_after_application_is_exactly_once(self):
        for index, checkpoint in enumerate(('batch_item_started', 'batch_item_applied_before_receipt')):
            with self.subTest(checkpoint=checkpoint):
                _, _, candidate = self.candidate(str(index))

                def crash(name, checkpoint=checkpoint):
                    if name == checkpoint:
                        raise RuntimeError('Simulated crash')

                service = self.batches(crash)
                batch = self.preview(service, candidate, key=f'crash-{index:08d}')
                self.confirm(service, batch)
                with self.assertRaises(RuntimeError):
                    service.run_next()
                service = self.batches()
                self.runtime.semantic_maintenance.recover()
                service.repository.recover()
                self.assertTrue(service.run_next())
                self.assertEqual(self.receipt(service, batch)['results'], {'APPLIED': 1})
                with closing(self.runtime.database.connect(readonly=True)) as connection:
                    self.assertEqual(connection.execute('SELECT count(*) FROM note_revisions WHERE candidate_id=?',
                                                        (candidate.candidate_id,)).fetchone()[0], 1)

    def test_external_approval_is_not_attributed_to_batch(self):
        _, _, candidate = self.candidate()
        service = self.batches()
        batch = self.preview(service, candidate)
        self.runtime.semantic_maintenance.approve(candidate.candidate_id)
        self.confirm(service, batch)
        service.run_next()
        self.assertEqual(self.receipt(service, batch)['results'], {'EXTERNALLY_RESOLVED': 1})

    def test_unconfirmed_batch_cannot_authorize_application(self):
        old, _, candidate = self.candidate()
        before = old.vault_path.read_bytes()
        service = self.batches()
        batch = self.preview(service, candidate)
        with self.assertRaises(KnowledgeConflict):
            self.runtime.semantic_maintenance.approve(candidate.candidate_id, actor='human:test',
                                                      review_batch_id=batch['batch_id'])
        self.assertEqual(old.vault_path.read_bytes(), before)

    def test_manual_lock_and_stale_revision_are_rechecked(self):
        old, _, candidate = self.candidate()
        before = old.vault_path.read_bytes()
        service = self.batches()
        batch = self.preview(service, candidate)
        self.runtime.semantic_repository.set_manual_lock(candidate.target_claim_id, True)
        blocked = self.preview(service, candidate, key='blocked-0001')
        self.assertEqual(blocked['results'], {'SKIPPED': 1})
        self.confirm(service, batch)
        service.run_next()
        self.assertEqual(self.receipt(service, batch)['results'], {'CONFLICT': 1})
        self.assertEqual(old.vault_path.read_bytes(), before)
        stale = service.preview(owner='human:test', key='stale-0001', selection=[
            {'candidate_id': candidate.candidate_id, 'expected_revision': 0}])
        self.assertEqual(stale['results'], {'SKIPPED': 1})
        with self.assertRaises(ValueError):
            self.preview(service, candidate, candidate, key='duplicate-0001')

    def test_two_candidates_for_same_note_are_both_excluded_from_plan(self):
        old, _, candidate = self.candidate()
        third = self.publish('third', '# Novedad\n\nProducto A versión 3.\n')
        service = self.runtime.semantic_maintenance
        ids = service.ingest_extraction(third.note_id, self.extraction(third, 'Producto A versión 3.',
                                                                      entities=('Producto A',)))
        other = next(self.runtime.semantic_repository.get_candidate(cid) for cid in ids
                     if self.runtime.semantic_repository.get_candidate(cid).target_note_id == old.note_id)
        other = service.compare(other.candidate_id, {'relation': 'SUPERSEDES', 'confidence': 0.99, 'impact': 'HIGH',
                                                     'rationale': 'Versión 3.',
                                                     'replacement_text': 'Producto A versión 3.'})
        batch = self.preview(self.batches(), candidate, other)
        self.assertEqual(batch['results'], {'SKIPPED': 2})
        self.assertTrue(all('misma nota' in row['blockers'][0] for row in batch['plan']['items']))

    def test_competing_approval_cannot_replace_intent_or_mark_it_conflicted(self):
        _, _, candidate = self.candidate()
        repo = self.runtime.semantic_repository

        def intent(name):
            if name == 'semantic_intent':
                # Simular una segunda petición que leyó PENDING_REVIEW antes de la reserva.
                with patch.object(repo, 'get_candidate', return_value=candidate):
                    with self.assertRaises(ValueError):
                        self.runtime.semantic_maintenance.approve(candidate.candidate_id)
                repo.mark_candidate(candidate.candidate_id, 'CONFLICT', reason='late-reader',
                                    expected_status='PENDING_REVIEW', expected_revision=1)
                self.assertEqual(repo.get_candidate(candidate.candidate_id).status, 'APPLYING')

        applied = SemanticMaintenanceService(repo,
            note_editor=self.runtime.semantic_maintenance.note_editor,
            checkpoint=intent).approve(candidate.candidate_id)
        self.assertEqual(applied.status, 'APPLIED')
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM note_revisions').fetchone()[0], 1)

    def test_api_batch_requires_review_scope_owner_and_matching_confirmation(self):
        _, _, candidate = self.candidate()
        auth = ApiAuth([{'name': 'reviewer', 'token': 'r' * 40, 'scopes': ['read', 'review']},
                        {'name': 'other', 'token': 'o' * 40, 'scopes': ['review']},
                        {'name': 'reader', 'token': 'v' * 40, 'scopes': ['read']}])
        headers = {'Authorization': 'Bearer ' + 'r' * 40, 'Idempotency-Key': 'batch-request-0001'}
        payload = {'selection': [{'candidate_id': candidate.candidate_id, 'expected_revision': 1}]}
        with httpx.Client(transport=httpx.WSGITransport(KnowledgeApi(self.runtime, auth)),
                          base_url='http://localhost/api/v1/') as client:
            self.assertEqual(client.post('review-batches/preview', json=payload, headers={
                **headers, 'Authorization': 'Bearer ' + 'v' * 40}).status_code, 403)
            response = client.post('review-batches/preview', json=payload, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            batch = response.json()
            url = 'review-batches/' + batch['batch_id']
            self.assertFalse(self.runtime.review_batches.run_next())
            self.assertEqual(client.get(url, headers={**headers, 'Authorization': 'Bearer ' + 'o' * 40})
                             .status_code, 404)
            self.assertEqual(client.post(url + '/confirm', json={'plan_hash': '0' * 64}, headers=headers)
                             .status_code, 409)
            confirmed = client.post(url + '/confirm', json={'plan_hash': batch['plan_hash']}, headers=headers)
            self.assertEqual(confirmed.status_code, 202, confirmed.text)
            self.runtime.review_batches.run_next()
            self.assertEqual(client.get(url, headers=headers).json()['results'], {'APPLIED': 1})
            repeated = client.post('review-batches/preview', json=payload, headers=headers)
            self.assertEqual(repeated.json()['batch_id'], batch['batch_id'])
            self.assertEqual(client.get('review-batches', headers=headers).json()['items'][0]['batch_id'],
                             batch['batch_id'])
            self.assertEqual(client.get('review-batches', headers={**headers, 'Authorization': 'Bearer ' + 'o' * 40})
                             .json()['items'], [])

    def test_interrupted_publication_is_visible_and_runtime_recovers_before_batch(self):
        _, _, candidate = self.candidate()

        def crash(name):
            if name == 'semantic_note_replaced':
                raise RuntimeError('Simulated crash after filesystem write')

        service = self.batches()
        service.maintenance = SemanticMaintenanceService(self.runtime.semantic_repository,
            note_editor=self.runtime.semantic_maintenance.note_editor, checkpoint=crash)
        batch = self.preview(service, candidate)
        self.confirm(service, batch)
        service.run_next()
        self.assertEqual(self.receipt(service, batch)['status'], 'RECOVERY_REQUIRED')
        self.assertFalse(service.run_next())
        self.runtime.recover_once(ingest_inbox=False)
        self.runtime.review_batches.run_next()
        self.assertEqual(self.receipt(service, batch)['results'], {'APPLIED': 1})
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate.candidate_id).review_batch_id,
                         batch['batch_id'])
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM note_revisions').fetchone()[0], 1)

    def test_worker_applies_confirmed_batch_without_broker(self):
        _, _, candidate = self.candidate()
        service = self.batches()
        batch = self.preview(service, candidate)
        self.confirm(service, batch)
        completed = threading.Event()
        finish = service.repository.finish_batch

        def finish_and_signal(batch_id):
            finish(batch_id)
            completed.set()

        worker = ReviewWorker(service)
        try:
            with patch.object(service.repository, 'finish_batch', side_effect=finish_and_signal):
                worker.start()
                self.assertTrue(completed.wait(5), 'El worker no completó el lote confirmado')
                self.assertEqual(self.receipt(service, batch)['results'], {'APPLIED': 1})
        finally:
            worker.stop()

    def test_widgets_preserve_multiselection_and_clear_previous_batch_details(self):
        try:
            probe = tk.Tk()
        except tk.TclError as error:
            if "Can't find a usable init.tcl" in str(error) or 'no display name' in str(error):
                self.skipTest('Tcl/Tk no disponible; checkpoint visual pendiente')
            raise
        probe.destroy()
        _, _, a = self.candidate('A')
        _, _, b = self.candidate('B')
        window = OrchestratorDashboard(self.runtime)
        window.withdraw()
        self.addCleanup(window.destroy)
        window._refresh_reviews()
        identifiers = (str(a.candidate_id), str(b.candidate_id))
        window.review_tree.selection_set(identifiers)
        window.review_tree.focus(identifiers[1])
        window._select_review()
        window._refresh_reviews()
        self.assertEqual(set(window.review_tree.selection()), set(identifiers))
        self.assertEqual(window._selected_review.candidate_id, b.candidate_id)
        dialog = ReviewBatchDialog(window, self.runtime.review_batches, selection=[
            {'candidate_id': a.candidate_id, 'expected_revision': 1}])
        dialog.withdraw()
        self.addCleanup(dialog._close)
        deadline = time.monotonic() + 5
        while dialog.batch is None and time.monotonic() < deadline:
            window.update()
            time.sleep(0.01)
        self.assertIsNotNone(dialog.batch)
        self.assertIn('Producto A versión 1.', dialog.before.get('1.0', 'end'))
        self.assertIn('Producto A versión 2.', dialog.proposed.get('1.0', 'end'))
        self.assertEqual(dialog.batch['status'], 'DRAFT')
        dialog._clear_batch()
        self.assertEqual(dialog.before.get('1.0', 'end-1c'), '')
        self.assertEqual(dialog.proposed.get('1.0', 'end-1c'), '')
        self.assertEqual(dialog.evidence.get('1.0', 'end-1c'), '')
