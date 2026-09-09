from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from knowledge_orchestrator.api.application import KnowledgeApi
from knowledge_orchestrator.api.auth import ApiAuth
from knowledge_orchestrator.integrations.obsidian_bridge import (
    ObsidianBridgeConflict,
    ObsidianBridgeUnavailable,
)
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.semantic_maintenance import SemanticContractError
from tests import test_phase_six_semantic_maintenance as phase_six
from tests import test_phase_twelve_knowledge_maintenance as phase_twelve


class ObsidianMaintenanceIntegrationTests(unittest.TestCase):
    setUp = phase_six.PhaseSixSemanticMaintenanceTests.setUp
    tearDown = phase_six.PhaseSixSemanticMaintenanceTests.tearDown
    publish = phase_six.PhaseSixSemanticMaintenanceTests.publish
    extraction = staticmethod(phase_six.PhaseSixSemanticMaintenanceTests.extraction)
    prepare_candidate = phase_six.PhaseSixSemanticMaintenanceTests.prepare_candidate
    decision = staticmethod(phase_twelve.PhaseTwelveKnowledgeMaintenanceTests.decision)

    def proposal(self):
        old, _, identifier, _, new_text = self.prepare_candidate()
        self.runtime.semantic_maintenance.compare(identifier, self.decision(new_text))
        return old, identifier

    def test_default_runtime_defers_without_bridge_and_recovers_without_direct_replace(self):
        old, identifier = self.proposal()
        before = old.vault_path.read_bytes()
        runtime = build_runtime(self.runtime.paths)
        self.assertIs(runtime.semantic_maintenance.note_editor, runtime.obsidian_connection)
        with self.assertRaises(ObsidianBridgeUnavailable):
            runtime.semantic_maintenance.approve(identifier)
        candidate = runtime.semantic_repository.get_candidate(identifier)
        self.assertEqual(candidate.status, 'APPLYING')
        self.assertFalse(candidate.temp_path.exists())
        runtime.recover_once(ingest_inbox=False)
        self.assertEqual(runtime.semantic_repository.get_candidate(identifier).status, 'APPLYING')
        self.assertEqual(old.vault_path.read_bytes(), before)
        runtime.semantic_maintenance.note_editor = self.runtime.semantic_maintenance.note_editor
        # Approval/recovery never call filesystem replacement, even when the bridge works.
        with patch('os.replace', side_effect=AssertionError('Unexpected direct replacement')):
            runtime.semantic_maintenance.recover()
        self.assertEqual(runtime.semantic_repository.get_candidate(identifier).status, 'APPLIED')

    def test_retry_uses_same_durable_request_and_does_not_duplicate_history(self):
        _, identifier = self.proposal()
        service = self.runtime.semantic_maintenance
        editor = service.note_editor
        with patch.object(editor, 'replace', side_effect=ObsidianBridgeUnavailable('Offline')) as call:
            with self.assertRaises(ObsidianBridgeUnavailable):
                service.approve(identifier)
            service.recover()
            requests = [item.kwargs['request_id'] for item in call.call_args_list]
        service.recover()
        service.recover()
        self.assertEqual(requests, [editor.requests[0]['request_id']] * 2)
        self.assertEqual(len(editor.requests), 1)
        applied = self.runtime.semantic_repository.get_candidate(identifier)
        self.assertEqual(applied.status, 'APPLIED')
        self.assertEqual(len(self.runtime.knowledge.repository.history(applied.target_claim_id)), 2)

    def test_api_explains_pending_operation_when_bridge_is_unavailable(self):
        old, identifier = self.proposal()
        runtime = build_runtime(self.runtime.paths)
        before = old.vault_path.read_bytes()
        token = 'fictitious-api-review-credential-0001'
        app = KnowledgeApi(runtime, ApiAuth([{'name': 'reviewer', 'token': token, 'scopes': ['read', 'review']}]))
        with httpx.Client(transport=httpx.WSGITransport(app), base_url='http://localhost') as client:
            response = client.post(f'/api/v1/review-tasks/{identifier}/approve',
                headers={'Authorization': 'Bearer ' + token, 'Idempotency-Key': 'bridge-approve-001'},
                json={'expected_revision': 1})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()['error']['code'], 'OBSIDIAN_UNAVAILABLE')
            receipt = client.get(f'/api/v1/review-tasks/{identifier}', headers={'Authorization': 'Bearer ' + token})
            self.assertEqual(receipt.json()['status'], 'APPLYING')
        self.assertNotIn(token, response.text)
        self.assertEqual(old.vault_path.read_bytes(), before)

    def test_response_lost_after_editor_writes_recovers_without_second_request(self):
        old, identifier = self.proposal()
        service = self.runtime.semantic_maintenance
        editor = service.note_editor
        replace = editor.replace

        def lose_response(*args, **kwargs):
            replace(*args, **kwargs)
            raise ObsidianBridgeUnavailable('Response lost')

        with patch.object(editor, 'replace', side_effect=lose_response):
            with self.assertRaises(ObsidianBridgeUnavailable):
                service.approve(identifier)
        result = old.vault_path.read_bytes()
        service.recover()
        self.assertEqual(old.vault_path.read_bytes(), result)
        self.assertEqual(len(editor.requests), 1)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(identifier).status, 'APPLIED')

    def test_ambiguous_bridge_receipt_requires_review_even_when_base_matches(self):
        old, identifier = self.proposal()
        service = self.runtime.semantic_maintenance
        before = old.vault_path.read_bytes()
        with patch.object(service.note_editor, 'replace', side_effect=ObsidianBridgeConflict('Review required')):
            with self.assertRaises(SemanticContractError):
                service.approve(identifier)
        service.recover()
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(identifier).status, 'CONFLICT')

    def test_reversion_keeps_intent_when_bridge_is_unavailable_and_retries_same_id(self):
        old, identifier = self.proposal()
        service = self.runtime.semantic_maintenance
        before = old.vault_path.read_bytes()
        candidate = service.approve(identifier)
        proposed = old.vault_path.read_bytes()
        reversions = self.runtime.maintenance_reversion
        plan = reversions.preview(identifier, expected_revision=candidate.proposal_revision,
                                 actor='human:test', key='bridge-reversion')
        with patch.object(service.note_editor, 'replace', side_effect=ObsidianBridgeUnavailable('Offline')) as call:
            with self.assertRaises(ObsidianBridgeUnavailable):
                reversions.confirm(plan['reversion_id'], actor='human:test', expected_plan_hash=plan['plan_hash'],
                                   reason='Restaurar la revisión anterior')
            reversions.recover()
            ids = [item.kwargs['request_id'] for item in call.call_args_list]
        self.assertEqual(old.vault_path.read_bytes(), proposed)
        reversions.recover()
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertEqual(reversions.repository.get(plan['reversion_id'], actor='human:test')['status'], 'APPLIED')
        self.assertEqual(ids, [service.note_editor.requests[-1]['request_id']] * 2)
        self.assertNotEqual(ids[0], service.note_editor.requests[0]['request_id'])
