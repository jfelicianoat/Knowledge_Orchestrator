from __future__ import annotations

import unittest
from unittest.mock import patch

from knowledge_orchestrator.integrations.obsidian_bridge import ObsidianBridgeUnavailable
from knowledge_orchestrator.services.semantic_maintenance import SemanticContractError
from tests import test_phase_six_semantic_maintenance as phase_six
from tests import test_phase_twelve_knowledge_maintenance as phase_twelve


class UnreadableMaintenanceNotesTests(unittest.TestCase):
    setUp = phase_six.PhaseSixSemanticMaintenanceTests.setUp
    tearDown = phase_six.PhaseSixSemanticMaintenanceTests.tearDown
    publish = phase_six.PhaseSixSemanticMaintenanceTests.publish
    extraction = staticmethod(phase_six.PhaseSixSemanticMaintenanceTests.extraction)
    decision = staticmethod(phase_twelve.PhaseTwelveKnowledgeMaintenanceTests.decision)

    def proposal(self, name):
        service = self.runtime.semantic_maintenance
        before, after = f'{name} versión 1.', f'{name} versión 2.'
        old = self.publish(f'{name}_old', f'# Estado\n\n{before}\n')
        service.ingest_extraction(old.note_id, self.extraction(old, before, entities=(name,)))
        new = self.publish(f'{name}_new', f'# Cambio\n\n{after}\n')
        ids = service.ingest_extraction(new.note_id, self.extraction(new, after, entities=(name,)))
        candidate = next(identifier for identifier in ids
                         if self.runtime.semantic_repository.get_candidate(identifier).target_note_id == old.note_id)
        service.compare(candidate, self.decision(after))
        return old, new, candidate

    def test_changed_encoding_before_approval_is_a_conflict_and_preserves_both_files(self):
        old, new, identifier = self.proposal('EncodingBefore')
        source = new.vault_path.read_bytes()
        changed = old.vault_path.read_bytes().decode('utf-8').encode('cp1252')
        old.vault_path.write_bytes(changed)
        with self.assertRaises(SemanticContractError):
            self.runtime.semantic_maintenance.approve(identifier)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(identifier).status, 'CONFLICT')
        self.assertEqual(old.vault_path.read_bytes(), changed)
        self.assertEqual(new.vault_path.read_bytes(), source)
        self.assertEqual(self.runtime.semantic_maintenance.note_editor.requests, [])

    def test_changed_encoding_after_intent_preserves_the_snapshot_and_human_edit(self):
        old, _, identifier = self.proposal('EncodingDuring')
        original = old.vault_path.read_bytes()
        changed = original.decode('utf-8').encode('cp1252')

        def edit(checkpoint):
            if checkpoint == 'semantic_intent':
                old.vault_path.write_bytes(changed)

        self.runtime.semantic_maintenance.checkpoint = edit
        with self.assertRaises(SemanticContractError):
            self.runtime.semantic_maintenance.approve(identifier)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(identifier).status, 'CONFLICT')
        self.assertEqual(old.vault_path.read_bytes(), changed)
        self.assertEqual(self.runtime.semantic_repository.revision_content(identifier).encode('utf-8'), original)
        self.assertEqual(self.runtime.semantic_maintenance.note_editor.requests, [])

    def test_unreadable_new_evidence_cannot_authorize_an_unchanged_target(self):
        old, new, identifier = self.proposal('EncodingEvidence')
        target = old.vault_path.read_bytes()
        changed = new.vault_path.read_bytes().decode('utf-8').encode('cp1252')
        new.vault_path.write_bytes(changed)
        with self.assertRaises(SemanticContractError):
            self.runtime.semantic_maintenance.approve(identifier)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(identifier).status, 'CONFLICT')
        self.assertEqual(old.vault_path.read_bytes(), target)
        self.assertEqual(new.vault_path.read_bytes(), changed)

    def test_recovery_continues_other_notes_after_an_unreadable_target(self):
        old, _, broken = self.proposal('BrokenRecovery')
        healthy, _, valid = self.proposal('HealthyRecovery')
        service = self.runtime.semantic_maintenance
        original = old.vault_path.read_bytes()
        with patch.object(service.note_editor, 'replace', side_effect=ObsidianBridgeUnavailable('Offline')):
            for identifier in (broken, valid):
                with self.assertRaises(ObsidianBridgeUnavailable):
                    service.approve(identifier)
        changed = original.decode('utf-8').encode('cp1252')
        old.vault_path.write_bytes(changed)
        service.recover()
        service.recover()
        self.assertEqual(self.runtime.semantic_repository.get_candidate(broken).status, 'CONFLICT')
        self.assertEqual(self.runtime.semantic_repository.get_candidate(valid).status, 'APPLIED')
        self.assertEqual(old.vault_path.read_bytes(), changed)
        self.assertEqual(self.runtime.semantic_repository.revision_content(broken).encode('utf-8'), original)
        self.assertEqual(len(service.note_editor.requests), 1)
        self.assertIn('HealthyRecovery versión 2.', healthy.vault_path.read_text(encoding='utf-8'))
