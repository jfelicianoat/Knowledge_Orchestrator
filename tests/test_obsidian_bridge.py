from __future__ import annotations

import hashlib
import json
import tempfile
import traceback
import unittest
from pathlib import Path

import httpx

from knowledge_orchestrator.integrations.obsidian_bridge import (
    ObsidianBridgeClient,
    ObsidianBridgeConflict,
    ObsidianBridgeUnavailable,
)


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class ObsidianBridgeTests(unittest.TestCase):
    token = 'fictitious-obsidian-credential-for-tests'

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.vault = Path(self.temporary.name)
        self.note = self.vault / 'Nota.md'
        self.note.write_bytes(b'base')
        self.arguments = {
            'base_hash': digest('base'), 'result_hash': digest('proposed'), 'request_id': digest('intent'),
        }

    def client(self, handler):
        return ObsidianBridgeClient(self.vault, self.token, transport=httpx.MockTransport(handler))

    def receipt(self, status='applied'):
        return {'status': status, 'request_id': digest('intent'), 'result_hash': digest('proposed')}

    def test_sends_bound_authenticated_intent_and_verifies_actual_note(self):
        def handler(request):
            self.assertEqual(request.headers['authorization'], f'Bearer {self.token}')
            self.assertEqual(request.headers['x-ko-vault-id'], client.vault_id)
            self.assertEqual(json.loads(request.content), {**self.arguments, 'path': 'Nota.md', 'content': 'proposed'})
            self.note.write_bytes(b'proposed')
            return httpx.Response(200, json=self.receipt())
        client = self.client(handler)
        self.assertEqual(client.replace(self.note, 'proposed', **self.arguments)['status'], 'applied')

    def test_stale_receipt_never_accepts_or_overwrites_a_human_edit(self):
        self.note.write_bytes(b'human edit')
        client = self.client(lambda request: httpx.Response(200, json=self.receipt('already_applied')))
        with self.assertRaises(ObsidianBridgeConflict):
            client.replace(self.note, 'proposed', **self.arguments)
        self.assertEqual(self.note.read_bytes(), b'human edit')

    def test_mismatched_receipt_and_wrong_vault_status_are_rejected(self):
        client = self.client(lambda request: httpx.Response(
            200, json={**self.receipt(), 'request_id': digest('other')},
        ))
        with self.assertRaises(ObsidianBridgeUnavailable):
            client.replace(self.note, 'proposed', **self.arguments)
        client = self.client(lambda request: httpx.Response(200, json={'protocol': 1, 'vault_id': 'other'}))
        with self.assertRaises(ObsidianBridgeConflict):
            client.status()

    def test_conflicts_and_unavailability_leave_note_intact_without_remote_error_content(self):
        for status in (401, 403, 404, 409, 500, 503):
            client = self.client(lambda request, status=status: httpx.Response(status, json={'message': self.token}))
            expected = ObsidianBridgeConflict if status in (404, 409) else ObsidianBridgeUnavailable
            with self.subTest(status=status), self.assertRaises(expected) as caught:
                client.replace(self.note, 'proposed', **self.arguments)
            self.assertNotIn(self.token, str(caught.exception))
            self.assertEqual(self.note.read_bytes(), b'base')

    def test_network_failure_suppresses_sensitive_exception_chain(self):
        def handler(request):
            raise httpx.ConnectError(self.token, request=request)
        client = self.client(handler)
        try:
            client.replace(self.note, 'proposed', **self.arguments)
        except ObsidianBridgeUnavailable:
            self.assertNotIn(self.token, traceback.format_exc())
        else:
            self.fail('Expected unavailable bridge')

    def test_rejects_remote_endpoints_outside_paths_and_wrong_content_before_sending(self):
        for url in ('http://localhost:8766', 'http://192.168.1.5:8766', 'http://127.0.0.1:8766/other'):
            with self.assertRaises(ValueError):
                ObsidianBridgeClient(self.vault, self.token, base_url=url)
        client = self.client(lambda request: self.fail('Unexpected request'))
        with self.assertRaises(ObsidianBridgeConflict):
            client.replace(self.vault.parent / 'outside.md', 'proposed', **self.arguments)
        with self.assertRaises(ObsidianBridgeConflict):
            client.replace(self.note, 'wrong', **self.arguments)
