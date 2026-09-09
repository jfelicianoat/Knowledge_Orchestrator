from __future__ import annotations

import json
import sqlite3
import time
import unittest
import uuid
from contextlib import closing
from unittest.mock import patch

import httpx

from knowledge_orchestrator.api.application import KnowledgeApi
from knowledge_orchestrator.api.auth import ApiAuth
from knowledge_orchestrator.domain.knowledge import KnowledgeConflict, KnowledgeState
from knowledge_orchestrator.domain.monitoring import FetchResult, SourceConfig, SourceItem
from knowledge_orchestrator.services.provenance import source_provenance
from knowledge_orchestrator.services.semantic_maintenance import SemanticContractError, SemanticMaintenanceService
from tests import test_phase_six_semantic_maintenance as phase_six


class PhaseTwelveKnowledgeMaintenanceTests(unittest.TestCase):
    setUp = phase_six.PhaseSixSemanticMaintenanceTests.setUp
    tearDown = phase_six.PhaseSixSemanticMaintenanceTests.tearDown
    publish = phase_six.PhaseSixSemanticMaintenanceTests.publish
    extraction = staticmethod(phase_six.PhaseSixSemanticMaintenanceTests.extraction)
    prepare_candidate = phase_six.PhaseSixSemanticMaintenanceTests.prepare_candidate

    @staticmethod
    def decision(replacement):
        return {'relation': 'SUPERSEDES', 'confidence': 0.99, 'impact': 'HIGH',
                'rationale': 'La nueva evidencia declara la versión.', 'replacement_text': replacement}

    def test_extraction_cannot_attach_an_invented_statement_to_a_valid_quote(self):
        note = self.publish('grounded_extraction', '# Documento\n\nVersión 1 disponible.\n')
        payload = self.extraction(note, 'Versión 1 disponible.')
        payload['claims'][0]['statement'] = 'Versión 99 disponible.'
        with self.assertRaises(SemanticContractError):
            self.runtime.semantic_maintenance.ingest_extraction(note.note_id, payload)
        self.assertEqual(self.runtime.semantic_repository.list_claims(), [])

    def test_model_confidence_cannot_authorize_unquoted_replacement(self):
        old, _, candidate_id, _, new_text = self.prepare_candidate()
        before = old.vault_path.read_bytes()
        with self.assertRaises(SemanticContractError):
            self.runtime.semantic_maintenance.compare(candidate_id, self.decision(new_text + ' Tiene cero errores.'))
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate_id).status, 'PENDING_COMPARISON')

    def test_new_evidence_modified_after_diff_blocks_approval_without_touching_target(self):
        old, new, candidate_id, _, new_text = self.prepare_candidate()
        before = old.vault_path.read_bytes()
        self.runtime.semantic_maintenance.compare(candidate_id, self.decision(new_text))
        new.vault_path.write_text(new.vault_path.read_text(encoding='utf-8') + '\nCambio humano.\n', encoding='utf-8')
        with self.assertRaises(SemanticContractError):
            self.runtime.semantic_maintenance.approve(candidate_id)
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate_id).status, 'CONFLICT')

    def test_external_edit_before_editor_callback_is_preserved(self):
        old, _, candidate_id, _, new_text = self.prepare_candidate()
        self.runtime.semantic_maintenance.compare(candidate_id, self.decision(new_text))
        human = old.vault_path.read_text(encoding='utf-8') + '\nAnotación humana.\n'

        editor = self.runtime.semantic_maintenance.note_editor
        replace = editor.replace

        def changed_during_write(path, content, **kwargs):
            old.vault_path.write_text(human, encoding='utf-8')
            return replace(path, content, **kwargs)

        with patch.object(editor, 'replace', side_effect=changed_during_write), \
                self.assertRaises(SemanticContractError):
            self.runtime.semantic_maintenance.approve(candidate_id)
        self.assertEqual(old.vault_path.read_text(encoding='utf-8'), human)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate_id).status, 'CONFLICT')

    def test_recovery_before_replace_revalidates_new_evidence(self):
        old, new, candidate_id, _, new_text = self.prepare_candidate()
        before = old.vault_path.read_bytes()
        self.runtime.semantic_maintenance.compare(candidate_id, self.decision(new_text))

        def crash(name):
            if name == 'semantic_intent':
                raise RuntimeError('simulated interruption')

        service = SemanticMaintenanceService(self.runtime.semantic_repository,
            note_editor=self.runtime.semantic_maintenance.note_editor, checkpoint=crash)
        with self.assertRaises(RuntimeError):
            service.approve(candidate_id)
        new.vault_path.write_text('Evidencia sustituida externamente', encoding='utf-8')
        self.runtime.semantic_maintenance.recover()
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate_id).status, 'CONFLICT')

    def test_overlapping_other_claim_requires_joint_proposal(self):
        old, _, candidate_id, old_text, new_text = self.prepare_candidate()
        self.runtime.semantic_maintenance.ingest_extraction(old.note_id, self.extraction(old, old_text[:-1]))
        self.runtime.semantic_maintenance.compare(candidate_id, self.decision(new_text))
        before = old.vault_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'solapado'):
            self.runtime.semantic_maintenance.approve(candidate_id)
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertTrue(all(claim.knowledge_state == 'CURRENT'
                            for claim in self.runtime.semantic_repository.list_claims(old.note_id)))

    def test_successor_reindexes_note_and_preserves_original_source_and_vector(self):
        old, new, candidate_id, old_text, new_text = self.prepare_candidate()
        service, repo = self.runtime.semantic_maintenance, self.runtime.semantic_repository
        original = repo.get_candidate(candidate_id).new_claim_id
        repo.record_embedding(original, 'test-space', [1.0, 0.0])
        service.compare(candidate_id, self.decision(new_text))
        applied = service.approve(candidate_id, expected_revision=1, actor='human:tester')
        projected = repo.get_claim(applied.applied_successor_id)
        self.assertEqual(projected.derived_from_claim_id, original)
        self.assertEqual(projected.source_capture_id, new.capture_id)
        document = old.vault_path.read_text(encoding='utf-8')
        self.assertEqual(document[projected.span_start:projected.span_end], new_text)
        self.assertIn(old_text, document.split('## Histórico')[1])
        evidence = self.runtime.knowledge.repository.evidence(projected.claim_id)[0]
        self.assertEqual(evidence['source_note_id'], new.note_id)
        self.assertEqual(evidence['source_content_hash'], new.content_hash)
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            vector = connection.execute('SELECT vector_json FROM claim_embeddings WHERE claim_id=?',
                                        (projected.claim_id,)).fetchone()[0]
        self.assertEqual(json.loads(vector), [1.0, 0.0])
        self.assertIn(projected.claim_id, [c['claim_id'] for c in self.runtime.knowledge_access.search('Producto')])
        self.assertEqual(self.runtime.knowledge.repository.history(projected.claim_id)[0]['actor'], 'human:tester')

    def test_reextraction_never_resurrects_history_or_changes_projected_provenance(self):
        old, _, candidate_id, old_text, new_text = self.prepare_candidate()
        service, repo = self.runtime.semantic_maintenance, self.runtime.semantic_repository
        service.compare(candidate_id, self.decision(new_text))
        applied = service.approve(candidate_id)
        before = repo.list_claims()
        evidence = self.runtime.knowledge.repository.evidence(applied.applied_successor_id)
        payload = self.extraction(old, new_text)
        payload['claims'] += self.extraction(old, old_text)['claims']
        self.assertEqual(service.ingest_extraction(old.note_id, payload), [])
        self.assertEqual(repo.list_claims(), before)
        self.assertEqual(self.runtime.knowledge.repository.evidence(applied.applied_successor_id), evidence)

    def test_existing_current_history_grows_without_duplicate_sections(self):
        old, _, first_id, old_text, new_text = self.prepare_candidate()
        service, repo = self.runtime.semantic_maintenance, self.runtime.semantic_repository
        service.compare(first_id, self.decision(new_text))
        first = service.approve(first_id)
        next_text = 'La versión estable de Producto X es 3.0.'
        next_note = self.publish('third_release', '# Actualización\n\n' + next_text + '\n')
        candidates = service.ingest_extraction(next_note.note_id, self.extraction(next_note, next_text))
        second = next(repo.get_candidate(identifier) for identifier in candidates
                      if repo.get_candidate(identifier).target_claim_id == first.applied_successor_id)
        compared = service.compare(second.candidate_id, self.decision(next_text))
        self.assertEqual(json.loads(compared.patch_json)['history_strategy'], 'existing_current_history')
        applied = service.approve(second.candidate_id)
        document = old.vault_path.read_text(encoding='utf-8')
        self.assertEqual(document.count('## Estado actual\n'), 1)
        self.assertEqual(document.count('## Histórico\n'), 1)
        current, history = document.split('## Histórico')
        self.assertIn(next_text, current)
        self.assertNotIn(new_text, current)
        self.assertEqual(history.count(old_text), 1)
        self.assertEqual(history.count(new_text), 1)
        chain = self.runtime.knowledge.repository.succession(applied.applied_successor_id)
        self.assertEqual({c.claim_id for c in chain},
                         {first.target_claim_id, first.applied_successor_id, applied.applied_successor_id})

    def test_complex_note_uses_snapshot_and_preserves_unaffected_claim_after_patch(self):
        old_text, new_text = 'Producto X versión 1.', 'Producto X versión 2.'
        unaffected_text = 'La política de soporte no cambia.'
        old = self.publish('complex_old', f'# Documento\n\n{old_text}\n\n{unaffected_text}\n')
        new = self.publish('complex_new', '# Documento\n\n' + new_text + '\n')
        service, repo = self.runtime.semantic_maintenance, self.runtime.semantic_repository
        payload = self.extraction(old, old_text)
        payload['claims'] += self.extraction(old, unaffected_text, entities=('Soporte',))['claims']
        service.ingest_extraction(old.note_id, payload)
        unaffected = repo.list_claims(old.note_id)[1]
        candidates = service.ingest_extraction(new.note_id, self.extraction(new, new_text))
        candidate = next(repo.get_candidate(identifier) for identifier in candidates
                         if repo.get_candidate(identifier).target_claim_id != unaffected.claim_id)
        before = old.vault_path.read_text(encoding='utf-8')
        compared = service.compare(candidate.candidate_id, self.decision(new_text))
        self.assertEqual(json.loads(compared.patch_json)['history_strategy'], 'revision_snapshot')
        service.approve(candidate.candidate_id)
        after = old.vault_path.read_text(encoding='utf-8')
        self.assertNotIn(old_text, after)
        self.assertEqual(repo.revision_content(candidate.candidate_id), before)
        refreshed = repo.get_claim(unaffected.claim_id)
        self.assertEqual(refreshed.knowledge_state, 'CURRENT')
        self.assertEqual(after[refreshed.span_start:refreshed.span_end], unaffected_text)

    def test_versioned_edits_retain_context_and_reject_stale_decisions(self):
        old, _, candidate_id, _, new_text = self.prepare_candidate()
        service = self.runtime.semantic_maintenance
        before = old.vault_path.read_bytes()
        service.compare(candidate_id, self.decision(new_text))
        edited = {**self.decision(new_text), 'rationale': 'Revisión humana de ambas evidencias.'}
        service.edit(candidate_id, edited, expected_revision=1, actor='human:editor')
        detail = service.proposal_detail(candidate_id)
        self.assertEqual(detail['revision'], 2)
        self.assertEqual(len(detail['versions']), 2)
        self.assertEqual(detail['versions'][0]['snapshot']['rationale'], self.decision(new_text)['rationale'])
        self.assertEqual(detail['versions'][1]['actor'], 'human:editor')
        self.assertEqual(detail['assessment']['planned_counts'], {'existing_claims': 1, 'new_claims': 1, 'notes': 1})
        self.assertFalse(detail['assessment']['autoapproval']['eligible'])
        self.assertEqual(old.vault_path.read_bytes(), before)
        with self.assertRaises(KnowledgeConflict):
            service.approve(candidate_id, expected_revision=1)
        with self.assertRaises(KnowledgeConflict):
            service.reject(candidate_id, expected_revision=1)
        with self.runtime.database.transaction() as connection, self.assertRaises(sqlite3.IntegrityError):
            connection.execute("UPDATE maintenance_proposal_versions SET actor='rewritten'")
        service.approve(candidate_id, expected_revision=2, actor='human:approver')
        self.assertEqual(service.proposal_detail(candidate_id)['reviewed_by'], 'human:approver')

    def test_legacy_diff_can_be_regenerated_without_rewriting_history(self):
        _, _, candidate_id, _, new_text = self.prepare_candidate()
        with self.runtime.database.transaction() as connection:
            connection.execute("UPDATE update_candidates SET status='PENDING_REVIEW' WHERE candidate_id=?",
                               (candidate_id,))
        service = self.runtime.semantic_maintenance
        self.assertTrue(service.proposal_detail(candidate_id)['requires_regeneration'])
        revised = service.edit(candidate_id, self.decision(new_text), expected_revision=0, actor='human:reviewer')
        self.assertEqual(revised.proposal_revision, 1)
        self.assertIn('source_hash', json.loads(revised.patch_json))
        self.assertEqual(service.approve(candidate_id, expected_revision=1).status, 'APPLIED')

    def publish_monitored(self, quote, *, trust_level, source_role):
        source_repo = self.runtime.sources.repository
        config = SourceConfig('Fuente ' + str(trust_level), 'web', 'https://example.org/' + uuid.uuid4().hex,
                              ingestion_policy='ingest', trust_level=trust_level, source_role=source_role)
        source = source_repo.create(config, actor='ui', key=uuid.uuid4().hex)
        now = time.time()
        job = next(job for job in source_repo.lease_due(now=now) if job['source_id'] == source['source_id'])
        source_repo.finish(job, FetchResult((SourceItem('release', 'Producto X', quote, config.location),)), now=now)
        self.runtime.sources.deliver_ready()
        self.runtime.api_ingestion.deliver_pending()
        inbox = next(self.runtime.paths.inbox.glob('*.md'))
        capture_id = inbox.stem
        self.assertTrue(self.runtime.ingestion.ingest(inbox).accepted)
        workflow_id = self.runtime.workflow_planner.plan_capture(capture_id)
        task = self.runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
        self.runtime.workflow_repository.apply_status(task.task_id, {
            'task_id': task.task_id, 'status': 'success',
            'result': {'assistant_content': '# Estado\n\n' + quote + '\n'},
            'error': None})
        self.runtime.workflow_planner.advance_workflow(workflow_id)
        self.assertEqual(self.runtime.publication.publish_ready(), 1)
        return next(note for note in self.runtime.publication_repository.list_notes_by_status('PUBLISHED')
                    if note.capture_id == capture_id)

    def contradiction(self, new_trust):
        old_text, new_text = 'Producto X utiliza el protocolo A.', 'Producto X utiliza el protocolo B.'
        old = self.publish_monitored(old_text, trust_level=95, source_role='official_documentation')
        new = self.publish_monitored(new_text, trust_level=new_trust,
                                     source_role='secondary' if new_trust < 80 else 'official_documentation')
        service = self.runtime.semantic_maintenance
        service.ingest_extraction(old.note_id, self.extraction(old, old_text))
        candidate_id = service.ingest_extraction(new.note_id, self.extraction(new, new_text))[0]
        before = old.vault_path.read_bytes()
        service.compare(candidate_id, {**self.decision(new_text), 'relation': 'CONTRADICTS'})
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(self.runtime.knowledge.repository.claims(), [])
        self.assertEqual({claim.knowledge_state for claim in self.runtime.semantic_repository.list_claims()},
                         {'DISPUTED'})
        return old, new, candidate_id

    def test_secondary_conflicting_source_requires_explicit_human_resolution(self):
        old, new, candidate_id = self.contradiction(30)
        service = self.runtime.semantic_maintenance
        detail = service.proposal_detail(candidate_id)
        self.assertIn('LOWER_TRUST_SOURCE_DISAGREES', detail['assessment']['risks'])
        self.assertEqual(detail['assessment']['source_trust'], [95, 30])
        applied = service.approve(candidate_id, expected_revision=1, actor='human:resolution')
        self.assertEqual(self.runtime.semantic_repository.get_claim(applied.target_claim_id).knowledge_state,
                         'HISTORICAL')
        self.assertEqual(self.runtime.knowledge.repository.claims(note_id=old.note_id)[0].source_capture_id,
                         new.capture_id)

    def test_two_high_trust_sources_do_not_resolve_by_trust_or_model_confidence(self):
        _, _, candidate_id = self.contradiction(90)
        detail = self.runtime.semantic_maintenance.proposal_detail(candidate_id)
        self.assertEqual(detail['status'], 'PENDING_REVIEW')
        self.assertIn('HIGH_TRUST_SOURCES_DISAGREE', detail['assessment']['risks'])
        self.assertFalse(detail['assessment']['autoapproval']['eligible'])

    def test_rejection_cannot_cancel_an_application_in_progress(self):
        _, _, candidate_id, _, new_text = self.prepare_candidate()
        self.runtime.semantic_maintenance.compare(candidate_id, self.decision(new_text))

        def checkpoint(name):
            if name == 'semantic_intent':
                with self.assertRaises(KnowledgeConflict):
                    self.runtime.semantic_repository.reject_candidate(candidate_id, expected_revision=1,
                                                                       actor='human:late', reason='Tarde')
                raise RuntimeError('simulated interruption')

        service = SemanticMaintenanceService(self.runtime.semantic_repository,
            note_editor=self.runtime.semantic_maintenance.note_editor, checkpoint=checkpoint)
        with self.assertRaises(RuntimeError):
            service.approve(candidate_id)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate_id).status, 'APPLYING')
        self.runtime.semantic_maintenance.recover()
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate_id).status, 'APPLIED')

    def test_api_review_scopes_revision_conflict_and_repeated_approval(self):
        _, _, candidate_id, _, new_text = self.prepare_candidate()
        self.runtime.semantic_maintenance.compare(candidate_id, self.decision(new_text))
        auth = ApiAuth([{'name': 'reviewer', 'token': 'r' * 40, 'scopes': ['read', 'review']},
                        {'name': 'reader', 'token': 'v' * 40, 'scopes': ['read', 'ingest']}])
        with httpx.Client(transport=httpx.WSGITransport(KnowledgeApi(self.runtime, auth)),
                          base_url='http://localhost/api/v1/') as client:
            headers = {'Authorization': 'Bearer ' + 'r' * 40, 'Idempotency-Key': 'review-request-0001'}
            path = f'review-tasks/{candidate_id}'
            denied = client.post(path + '/approve', json={'expected_revision': 1},
                                 headers={**headers, 'Authorization': 'Bearer ' + 'v' * 40})
            self.assertEqual(denied.status_code, 403)
            edited = client.patch(path, json={**self.decision(new_text), 'expected_revision': 1}, headers=headers)
            self.assertEqual(edited.status_code, 200, edited.text)
            self.assertEqual(edited.json()['revision'], 2)
            stale = client.post(path + '/approve', json={'expected_revision': 1}, headers=headers)
            self.assertEqual(stale.status_code, 409)
            applied = client.post(path + '/approve', json={'expected_revision': 2}, headers=headers)
            self.assertEqual(applied.status_code, 200, applied.text)
            repeated = client.post(path + '/approve', json={'expected_revision': 2}, headers=headers)
            self.assertEqual(repeated.json()['applied_successor_id'], applied.json()['applied_successor_id'])
            self.assertEqual(len(self.runtime.semantic_repository.list_claims()), 3)
            self.assertEqual(client.post(path + '/reject', json={'expected_revision': 2}, headers=headers).status_code,
                             409)


    def prepare_derived_evidence_candidate(self):
        old, source, first_id, _, new_text = self.prepare_candidate()
        service, repo = self.runtime.semantic_maintenance, self.runtime.semantic_repository
        service.compare(first_id, self.decision(new_text))
        first = service.approve(first_id)
        projected = repo.get_claim(first.applied_successor_id)
        target_text = 'Producto X versión previa.'
        target = self.publish('derived_target', '# Estado\n\n' + target_text + '\n')
        service.ingest_extraction(target.note_id, self.extraction(target, target_text))
        target_claim = repo.list_claims(target.note_id)[0]
        candidate = repo.create_candidate(target_claim, projected, retrieval_reason='entity')
        service.compare(candidate.candidate_id, self.decision(new_text))
        return source, target, candidate.candidate_id, projected, first.new_claim_id

    def test_changed_original_evidence_invalidates_projection_and_blocks_later_approval(self):
        source, target, candidate_id, projected, _ = self.prepare_derived_evidence_candidate()
        before = target.vault_path.read_bytes()
        source.vault_path.write_text('Edición humana en la evidencia original.', encoding='utf-8')
        self.runtime.knowledge.reconcile()
        self.assertEqual(self.runtime.semantic_repository.get_claim(projected.claim_id).knowledge_state,
                         'REVIEW_REQUIRED')
        self.assertNotIn(projected.claim_id, {c.claim_id for c in self.runtime.knowledge.repository.claims()})
        with self.assertRaises(SemanticContractError):
            self.runtime.semantic_maintenance.approve(candidate_id)
        self.assertEqual(target.vault_path.read_bytes(), before)
        history = self.runtime.knowledge.repository.history(projected.claim_id)
        self.assertEqual(history[-1]['actor'], 'system:reconciliation')
        self.runtime.knowledge.reconcile()
        self.assertEqual(self.runtime.knowledge.repository.history(projected.claim_id), history)

    def test_application_reserves_original_evidence_state_lock_and_publication(self):
        source, _, candidate_id, _, original_id = self.prepare_derived_evidence_candidate()
        service, repo = self.runtime.semantic_maintenance, self.runtime.semantic_repository
        next_text = 'La versión estable de Producto X es 3.0.'
        next_note = self.publish('concurrent_source', '# Estado\n\n' + next_text + '\n')
        candidates = service.ingest_extraction(next_note.note_id, self.extraction(next_note, next_text))
        other = next(repo.get_candidate(identifier) for identifier in candidates
                     if repo.get_candidate(identifier).target_claim_id == original_id)
        service.compare(other.candidate_id, self.decision(next_text))
        before = source.vault_path.read_bytes()

        def checkpoint(name):
            if name != 'semantic_intent':
                return
            original = repo.get_claim(original_id)
            with self.assertRaises(KnowledgeConflict):
                self.runtime.knowledge.repository.review_state(
                    original_id, KnowledgeState.DISPUTED, expected_revision=original.revision,
                    actor='human:other', reason='Revisión concurrente de origen')
            with self.assertRaises(ValueError):
                repo.set_manual_lock(original_id, True)
            with self.assertRaises(KnowledgeConflict):
                service.approve(other.candidate_id)
            self.assertEqual(source.vault_path.read_bytes(), before)

        applied = SemanticMaintenanceService(repo,
            note_editor=self.runtime.semantic_maintenance.note_editor, checkpoint=checkpoint).approve(candidate_id)
        self.assertEqual(applied.status, 'APPLIED')
        self.assertEqual(service.approve(other.candidate_id).status, 'APPLIED')
        self.runtime.knowledge.reconcile()
        self.assertEqual(repo.get_claim(applied.applied_successor_id).knowledge_state, 'REVIEW_REQUIRED')

    def test_locked_projection_keeps_manual_state_but_stale_origin_is_not_current(self):
        source, _, _, projected, _ = self.prepare_derived_evidence_candidate()
        repo = self.runtime.semantic_repository
        repo.set_manual_lock(projected.claim_id, True)
        history = self.runtime.knowledge.repository.history(projected.claim_id)
        source.vault_path.write_text('Origen editado.', encoding='utf-8')
        self.runtime.knowledge.reconcile()
        self.assertTrue(repo.get_claim(projected.claim_id).manual_lock)
        self.assertEqual(self.runtime.knowledge.repository.history(projected.claim_id), history)
        self.assertNotIn(projected.claim_id, {c.claim_id for c in self.runtime.knowledge.repository.claims()})

    def test_capture_tampering_cannot_inherit_monitoring_trust(self):
        note = self.publish_monitored('Producto X disponible.', trust_level=95,
                                      source_role='official_documentation')
        self.assertEqual(source_provenance(self.runtime.database, note.capture_id)['monitoring']['trust_level'], 95)
        with self.runtime.database.transaction() as connection:
            connection.execute('UPDATE captures SET sha256=? WHERE capture_id=?', ('0' * 64, note.capture_id))
        provenance = source_provenance(self.runtime.database, note.capture_id)
        self.assertNotIn('monitoring', provenance)
        self.assertEqual(provenance['provenance_warning'], 'CAPTURE_CHANGED_AFTER_RECEIPT')

    def test_api_claim_state_review_requires_scope_revision_reason_and_preserves_note(self):
        old, _, candidate_id, _, _ = self.prepare_candidate()
        claim_id = self.runtime.semantic_repository.get_candidate(candidate_id).target_claim_id
        before = old.vault_path.read_bytes()
        auth = ApiAuth([{'name': 'reviewer', 'token': 'r' * 40, 'scopes': ['read', 'review']},
                        {'name': 'reader', 'token': 'v' * 40, 'scopes': ['read']}])
        with httpx.Client(transport=httpx.WSGITransport(KnowledgeApi(self.runtime, auth)),
                          base_url='http://localhost/api/v1/') as client:
            path = f'claims/{claim_id}/knowledge-state'
            payload = {'state': 'DISPUTED', 'expected_revision': 1, 'reason': 'Evidencias por revisar.'}
            headers = {'Authorization': 'Bearer ' + 'r' * 40}
            self.assertEqual(client.patch(path, json=payload,
                                          headers={'Authorization': 'Bearer ' + 'v' * 40}).status_code, 403)
            reviewed = client.patch(path, json=payload, headers=headers)
            self.assertEqual(reviewed.status_code, 200, reviewed.text)
            self.assertEqual(reviewed.json()['knowledge_state'], 'DISPUTED')
            self.assertEqual(reviewed.json()['revision'], 2)
            self.assertEqual(client.patch(path, json=payload, headers=headers).status_code, 409)
            invalid = {**payload, 'expected_revision': 2, 'state': 'SUPERSEDED'}
            self.assertEqual(client.patch(path, json=invalid, headers=headers).status_code, 400)
            self.assertEqual(client.patch(path, json={**payload, 'reason': ' '}, headers=headers).status_code, 400)
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(self.runtime.knowledge.repository.history(claim_id)[-1]['actor'], 'reviewer')


if __name__ == '__main__':
    unittest.main()
