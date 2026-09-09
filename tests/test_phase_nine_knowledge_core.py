from __future__ import annotations

import sqlite3
import unittest
from contextlib import closing
from importlib.resources import files

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict, KnowledgeState
from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.repositories.knowledge_repository import KnowledgeRepository
from knowledge_orchestrator.services.semantic_maintenance import SemanticContractError, SemanticMaintenanceService
from tests import test_phase_six_semantic_maintenance as phase_six


class PhaseNineKnowledgeCoreTests(unittest.TestCase):
    setUp = phase_six.PhaseSixSemanticMaintenanceTests.setUp
    tearDown = phase_six.PhaseSixSemanticMaintenanceTests.tearDown
    publish = phase_six.PhaseSixSemanticMaintenanceTests.publish
    extraction = staticmethod(phase_six.PhaseSixSemanticMaintenanceTests.extraction)
    prepare_candidate = phase_six.PhaseSixSemanticMaintenanceTests.prepare_candidate

    def proposal(self, candidate_id, replacement):
        return self.runtime.semantic_maintenance.compare(candidate_id, {
            'relation': 'SUPERSEDES', 'confidence': 0.95, 'impact': 'HIGH',
            'rationale': 'La evidencia nueva identifica una versión posterior.', 'replacement_text': replacement,
        })

    def test_approved_successor_preserves_unaffected_claim_and_full_evidence(self):
        old_note, _, candidate_id, old_text, new_text = self.prepare_candidate()
        # Un segundo span no sustituido de la misma nota debe conservar su identidad.
        quote = '# Estado'
        self.runtime.semantic_maintenance.ingest_extraction(old_note.note_id, self.extraction(old_note, quote))
        unaffected = self.runtime.semantic_repository.list_claims(old_note.note_id)[1]
        before = old_note.vault_path.read_text(encoding='utf-8')
        candidate = self.proposal(candidate_id, new_text)
        self.runtime.semantic_maintenance.approve(candidate_id)
        knowledge = self.runtime.knowledge.repository
        current = knowledge.claims()
        self.assertNotIn(candidate.target_claim_id, [c.claim_id for c in current])
        self.assertIn(candidate.new_claim_id, [c.claim_id for c in current])
        self.assertIn(unaffected.claim_id, [c.claim_id for c in current])
        historical = knowledge.claims(state='historical')
        self.assertEqual(len(historical), 1)
        old = historical[0]
        self.assertEqual(old.knowledge_state, 'SUPERSEDED')
        self.assertEqual(old.statement, old_text)
        applied = self.runtime.semantic_repository.get_candidate(candidate_id)
        self.assertEqual(old.superseded_by, applied.applied_successor_id)
        successor = self.runtime.semantic_repository.get_claim(applied.applied_successor_id)
        self.assertEqual(successor.derived_from_claim_id, candidate.new_claim_id)
        self.assertEqual(successor.note_id, old_note.note_id)
        self.assertIsNotNone(old.valid_until)
        self.assertEqual(old.revision, 2)
        self.assertEqual(knowledge.evidence(old.claim_id)[0]['quote'], old_text)
        self.assertEqual(self.runtime.semantic_repository.revision_content(candidate_id), before)
        self.assertEqual([h['to_state'] for h in knowledge.history(old.claim_id)], ['CURRENT', 'SUPERSEDED'])
        self.assertEqual({c.claim_id for c in knowledge.succession(successor.claim_id)},
                         {candidate.target_claim_id, successor.claim_id})

    def test_entity_links_and_reindex_are_idempotent_without_resurrecting_history(self):
        old_note, new_note, candidate_id, _, new_text = self.prepare_candidate()
        self.proposal(candidate_id, new_text)
        self.runtime.semantic_maintenance.approve(candidate_id)
        knowledge = self.runtime.knowledge.repository
        entity = knowledge.entities()[0]
        self.assertEqual(knowledge.entity(entity.entity_id), entity)
        before = knowledge.claims(state='all')
        self.runtime.semantic_maintenance.ingest_extraction(new_note.note_id, self.extraction(new_note, new_text))
        self.assertEqual(knowledge.claims(state='all'), before)
        self.assertEqual(len(knowledge.entities()), 1)
        self.assertEqual(len(knowledge.claims(entity_id=entity.entity_id)), 2)
        self.assertEqual(len(knowledge.claims(entity_id=entity.entity_id, state='historical')), 1)
        projected = knowledge.claims(note_id=old_note.note_id)
        self.assertEqual([claim.statement for claim in projected], [new_text])
        self.assertIsNotNone(projected[0].derived_from_claim_id)

    def test_review_states_require_reason_revision_and_never_reactivate_historical_claim(self):
        _, _, candidate_id, _, new_text = self.prepare_candidate()
        candidate = self.proposal(candidate_id, new_text)
        knowledge = self.runtime.knowledge.repository
        claim_id = candidate.target_claim_id
        for revision, state in enumerate([
            KnowledgeState.DISPUTED, KnowledgeState.UNCERTAIN, KnowledgeState.REVIEW_REQUIRED, KnowledgeState.CURRENT,
        ], start=1):
            knowledge.review_state(claim_id, state, expected_revision=revision, actor='human:test', reason='Revisión')
            selected = knowledge.claims(state=state.value)
            self.assertIn(claim_id, [c.claim_id for c in selected])
            if state != KnowledgeState.CURRENT:
                self.assertNotIn(claim_id, [c.claim_id for c in knowledge.claims()])
        with self.assertRaises(KnowledgeConflict):
            knowledge.review_state(claim_id, KnowledgeState.DISPUTED,
                                   expected_revision=1, actor='human:test', reason='Revisión obsoleta')
        with self.assertRaises(ValueError):
            knowledge.review_state(claim_id, KnowledgeState.DISPUTED,
                                   expected_revision=5, actor='human:test', reason='')
        self.runtime.semantic_maintenance.approve(candidate_id)
        with self.assertRaises(KnowledgeConflict):
            knowledge.review_state(claim_id, KnowledgeState.CURRENT,
                                   expected_revision=6, actor='human:test', reason='Reactivar')

    def test_manual_lock_after_diff_prevents_note_and_claim_changes(self):
        note, _, candidate_id, _, new_text = self.prepare_candidate()
        candidate = self.proposal(candidate_id, new_text)
        before = note.vault_path.read_bytes()
        self.runtime.semantic_repository.set_manual_lock(candidate.target_claim_id, True)
        with self.assertRaises(ValueError):
            self.runtime.semantic_maintenance.approve(candidate_id)
        with self.assertRaises(KnowledgeConflict):
            self.runtime.knowledge.repository.review_state(
                candidate.target_claim_id, KnowledgeState.DISPUTED,
                expected_revision=1, actor='human:test', reason='Contradicción',
            )
        self.assertEqual(note.vault_path.read_bytes(), before)
        self.assertEqual(len(self.runtime.knowledge.repository.history(candidate.target_claim_id)), 1)

    def test_change_outside_patch_after_diff_is_conflict(self):
        note, _, candidate_id, _, new_text = self.prepare_candidate()
        self.proposal(candidate_id, new_text)
        edited = note.vault_path.read_text(encoding='utf-8') + '\nEdición humana fuera del span.\n'
        note.vault_path.write_text(edited, encoding='utf-8')
        with self.assertRaises(SemanticContractError):
            self.runtime.semantic_maintenance.approve(candidate_id)
        self.assertEqual(note.vault_path.read_text(encoding='utf-8'), edited)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate_id).status, 'CONFLICT')

    def test_edit_between_intent_and_replace_is_not_overwritten(self):
        note, _, candidate_id, _, new_text = self.prepare_candidate()
        self.proposal(candidate_id, new_text)
        edited = note.vault_path.read_text(encoding='utf-8') + '\nNueva edición humana.\n'

        def checkpoint(name):
            if name == 'semantic_intent':
                note.vault_path.write_text(edited, encoding='utf-8')

        service = SemanticMaintenanceService(self.runtime.semantic_repository,
            note_editor=self.runtime.semantic_maintenance.note_editor, checkpoint=checkpoint)
        with self.assertRaises(SemanticContractError):
            service.approve(candidate_id)
        self.assertEqual(note.vault_path.read_text(encoding='utf-8'), edited)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate_id).status, 'CONFLICT')

    def test_recovery_registers_exactly_one_temporal_transition(self):
        _, _, candidate_id, _, new_text = self.prepare_candidate()
        candidate = self.proposal(candidate_id, new_text)

        def checkpoint(name):
            if name == 'semantic_note_replaced':
                raise phase_six.SimulatedCrash(name)

        service = SemanticMaintenanceService(self.runtime.semantic_repository,
            note_editor=self.runtime.semantic_maintenance.note_editor, checkpoint=checkpoint)
        with self.assertRaises(phase_six.SimulatedCrash):
            service.approve(candidate_id)
        self.runtime.semantic_maintenance.recover()
        self.runtime.semantic_maintenance.recover()
        history = self.runtime.knowledge.repository.history(candidate.target_claim_id)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[-1]['candidate_id'], candidate_id)
        applied = self.runtime.semantic_repository.get_candidate(candidate_id)
        self.assertEqual(history[-1]['superseded_by'], applied.applied_successor_id)

    def test_reconciliation_excludes_external_changes_without_touching_locked_claim_or_file(self):
        note, _, candidate_id, _, _ = self.prepare_candidate(locked=True)
        candidate = self.runtime.semantic_repository.get_candidate(candidate_id)
        original = note.vault_path.read_bytes()
        before = self.runtime.semantic_repository.get_claim(candidate.target_claim_id)
        edited = original + b'\nExternal change\n'
        note.vault_path.write_bytes(edited)
        self.assertEqual(self.runtime.knowledge.reconcile()[note.note_id], 'CONFLICT')
        knowledge = self.runtime.knowledge.repository
        self.assertNotIn(before.claim_id, [c.claim_id for c in knowledge.claims()])
        self.assertEqual(self.runtime.semantic_repository.get_claim(before.claim_id), before)
        self.assertEqual(note.vault_path.read_bytes(), edited)
        note.vault_path.write_bytes(original)
        self.assertEqual(self.runtime.knowledge.reconcile()[note.note_id], 'IN_SYNC')
        self.assertIn(before.claim_id, [c.claim_id for c in knowledge.claims()])
        note.vault_path.unlink()
        self.assertEqual(self.runtime.knowledge.reconcile()[note.note_id], 'MISSING')
        self.assertNotIn(before.claim_id, [c.claim_id for c in knowledge.claims()])

    def test_history_is_immutable_and_pagination_and_states_are_validated(self):
        self.prepare_candidate()
        knowledge = self.runtime.knowledge.repository
        with self.assertRaises(sqlite3.IntegrityError), self.runtime.database.transaction() as connection:
            connection.execute("UPDATE claim_state_history SET reason = 'changed'")
        with self.assertRaises(sqlite3.IntegrityError), self.runtime.database.transaction() as connection:
            connection.execute('DELETE FROM claim_state_history')
        with self.assertRaises(ValueError):
            knowledge.claims(state='latest-ish')
        with self.assertRaises(ValueError):
            knowledge.claims(limit=1001)
        self.assertEqual(len(knowledge.claims(limit=1, offset=1)), 1)

    def test_migration_preserves_legacy_entities_states_spans_evidence_and_ids(self):
        database = Database(self.root / 'legacy.db')
        migration_root = files('knowledge_orchestrator').joinpath('migrations')
        with closing(database.connect()) as connection:
            connection.execute('CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT)')
            for path in sorted(migration_root.iterdir(), key=lambda p: p.name):
                if path.name.endswith('.sql') and int(path.name.split('_')[0]) <= 11:
                    connection.executescript(path.read_text(encoding='utf-8'))
                    connection.execute('INSERT INTO schema_migrations(version) VALUES (?)',
                                       (int(path.name.split('_')[0]),))
                    connection.commit()
            connection.execute(
                "INSERT INTO captures(capture_id, contract_version, source_type, title, status, sha256, "
                "original_filename, metadata_json, transcript_content) "
                "VALUES ('legacy', '1.0', 'generic', 'Legacy', 'COMPLETED', 'abc', 'legacy.md', '{}', 'text')"
            )
            connection.execute("INSERT INTO notes(note_id, capture_id, status) VALUES (1, 'legacy', 'PUBLISHED')")
            for claim_id, status in enumerate(['ACTIVE', 'SUPERSEDED', 'RETRACTED'], start=1):
                connection.execute(
                    'INSERT INTO knowledge_claims(claim_id, note_id, source_capture_id, statement, '
                    'normalized_statement, claim_type, volatility, span_start, span_end, entities_json, status) '
                    "VALUES (?, 1, 'legacy', ?, ?, 'FACT', 'LOW', ?, ?, '[\"Producto X\"]', ?)",
                    (claim_id, f'claim {claim_id}', f'claim {claim_id}', claim_id * 10, claim_id * 10 + 5, status),
                )
                connection.execute(
                    'INSERT INTO evidence_links(claim_id, source_capture_id, quote, span_start, span_end, source_path) '
                    "VALUES (?, 'legacy', 'quote', 10, 15, 'legacy.md')", (claim_id,),
                )
            connection.commit()
        database.initialize()
        database.initialize()
        knowledge = KnowledgeRepository(database)
        self.assertEqual([c.claim_id for c in knowledge.claims(state='all')], [1, 2, 3])
        self.assertEqual([c.knowledge_state for c in knowledge.claims(state='all')],
                         ['CURRENT', 'SUPERSEDED', 'HISTORICAL'])
        self.assertEqual(len(knowledge.entities()), 1)
        for claim in knowledge.claims(state='all'):
            self.assertEqual(claim.span_start, claim.claim_id * 10)
            self.assertEqual(knowledge.evidence(claim.claim_id)[0]['quote'], 'quote')
            self.assertEqual(len(knowledge.history(claim.claim_id)), 1)
        with closing(database.connect()) as connection:
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
