from __future__ import annotations

import unittest
from unittest.mock import patch

from knowledge_orchestrator.integrations.obsidian_bridge import ObsidianBridgeUnavailable
from knowledge_orchestrator.services.semantic_maintenance import SemanticContractError
from tests import test_maintenance_unreadable_notes as unreadable


class WindowsMaintenanceNewlinesTests(unittest.TestCase):
    setUp = unreadable.UnreadableMaintenanceNotesTests.setUp
    tearDown = unreadable.UnreadableMaintenanceNotesTests.tearDown
    publish = unreadable.UnreadableMaintenanceNotesTests.publish
    extraction = staticmethod(unreadable.UnreadableMaintenanceNotesTests.extraction)
    decision = staticmethod(unreadable.UnreadableMaintenanceNotesTests.decision)
    proposal = unreadable.UnreadableMaintenanceNotesTests.proposal

    def test_recovery_cannot_confirm_a_result_edited_to_crlf_after_a_lost_response(self):
        old, _, identifier = self.proposal('NewlinesResult')
        service = self.runtime.semantic_maintenance
        original = old.vault_path.read_bytes()
        replace = service.note_editor.replace

        def lose_response(*args, **kwargs):
            replace(*args, **kwargs)
            raise ObsidianBridgeUnavailable('Lost response')

        with patch.object(service.note_editor, 'replace', side_effect=lose_response):
            with self.assertRaises(ObsidianBridgeUnavailable):
                service.approve(identifier)
        edited = old.vault_path.read_bytes().replace(b'\n', b'\r\n')
        old.vault_path.write_bytes(edited)
        service.recover()
        service.recover()
        candidate = self.runtime.semantic_repository.get_candidate(identifier)
        self.assertEqual(candidate.status, 'CONFLICT')
        self.assertEqual(old.vault_path.read_bytes(), edited)
        self.assertEqual(self.runtime.semantic_repository.revision_content(identifier).encode('utf-8'), original)
        self.assertEqual(len(service.note_editor.requests), 1)

    def test_recovery_rejects_changed_base_bytes_before_contacting_the_editor(self):
        old, _, identifier = self.proposal('NewlinesBase')
        service = self.runtime.semantic_maintenance
        with patch.object(service.note_editor, 'replace', side_effect=ObsidianBridgeUnavailable('Offline')):
            with self.assertRaises(ObsidianBridgeUnavailable):
                service.approve(identifier)
        edited = old.vault_path.read_bytes().replace(b'\n', b'\r\n')
        old.vault_path.write_bytes(edited)
        service.recover()
        self.assertEqual(self.runtime.semantic_repository.get_candidate(identifier).status, 'CONFLICT')
        self.assertEqual(service.note_editor.requests, [])
        self.assertEqual(old.vault_path.read_bytes(), edited)

    def test_changed_evidence_newlines_cannot_silently_authorize_an_update(self):
        old, new, identifier = self.proposal('NewlinesEvidence')
        original = old.vault_path.read_bytes()
        edited = new.vault_path.read_bytes().replace(b'\n', b'\r\n')
        new.vault_path.write_bytes(edited)
        with self.assertRaises(SemanticContractError):
            self.runtime.semantic_maintenance.approve(identifier)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(identifier).status, 'CONFLICT')
        self.assertEqual(old.vault_path.read_bytes(), original)
        self.assertEqual(new.vault_path.read_bytes(), edited)
        self.assertEqual(self.runtime.semantic_maintenance.note_editor.requests, [])

    def test_crlf_documents_use_exact_offsets_through_approval_and_reversion(self):
        service = self.runtime.semantic_maintenance
        old_text, new_text = 'Producto CRLF versión 1.', 'Producto CRLF versión 2.'
        old = self.publish('crlf_old', f'# Estado\r\n\r\n{old_text}\r\n')
        new = self.publish('crlf_new', f'# Cambio\r\n\r\n{new_text}\r\n')
        original = old.vault_path.read_bytes()
        self.assertIn(b'\r\n', original)
        for note, quote in ((old, old_text), (new, new_text)):
            payload = self.extraction(note, quote, entities=('Producto CRLF',))
            document = note.vault_path.read_bytes().decode('utf-8')
            payload['claims'][0].update(span_start=document.index(quote), span_end=document.index(quote) + len(quote))
            ids = service.ingest_extraction(note.note_id, payload)
        identifier = ids[0]
        candidate = service.compare(identifier, self.decision(new_text))
        service.approve(identifier)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(identifier).status, 'APPLIED')
        self.assertEqual(self.runtime.semantic_repository.revision_content(identifier).encode('utf-8'), original)
        reversions = self.runtime.maintenance_reversion
        plan = reversions.preview(identifier, expected_revision=candidate.proposal_revision,
                                 actor='human:test', key='crlf-reversion')
        result = reversions.confirm(plan['reversion_id'], actor='human:test',
                                    expected_plan_hash=plan['plan_hash'], reason='Restore original CRLF note')
        self.assertEqual(result['status'], 'APPLIED')
        self.assertEqual(old.vault_path.read_bytes(), original)
