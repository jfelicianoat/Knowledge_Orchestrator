from __future__ import annotations

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.integrations.obsidian_bridge import ObsidianBridgeUnavailable
from knowledge_orchestrator.services.obsidian_connection import ObsidianConnection


class ObsidianConnectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.paths = PipelinePaths.under(Path(temporary.name))
        self.paths.ensure_directories()
        self.store = ObsidianConnection(self.paths, protect=lambda b: b[::-1], unprotect=lambda b: b[::-1])
        self.token = 'fictitious-bridge-credential-for-storage-tests'

    def test_atomic_configuration_rotation_and_no_plaintext_secret(self):
        self.store.save('http://127.0.0.1:8766', token=self.token)
        self.assertEqual(self.store.client()._token, self.token)
        self.assertNotIn(self.token, self.store.path.read_text())
        self.store.save('http://127.0.0.1:9001')
        self.assertEqual(self.store.client()._token, self.token)
        self.assertEqual(self.store.configured_url(), 'http://127.0.0.1:9001')
        self.store.save('http://127.0.0.1:9001', token='different-fictitious-token-' * 2)
        self.assertNotEqual(self.store.client()._token, self.token)

    def test_new_connection_uses_a_separate_default_without_saving_credentials(self):
        self.assertEqual(self.store.configured_url(), 'http://127.0.0.1:8767')
        self.assertFalse(self.store.path.exists())
        with self.assertRaises(ObsidianBridgeUnavailable):
            self.store.client()

    def test_existing_plugin_port_is_suggested_but_saved_connection_takes_precedence(self):
        settings = self.paths.obsidian_vault / '.obsidian/plugins/knowledge-orchestrator-bridge/data.json'
        settings.parent.mkdir(parents=True)
        content = json.dumps({'port': 8766, 'secretName': 'private-label', 'enabled': True}).encode()
        settings.write_bytes(content)
        self.assertEqual(self.store.configured_url(), 'http://127.0.0.1:8766')
        self.assertFalse(self.store.path.exists())
        self.store.save('http://127.0.0.1:9001', token=self.token)
        protected = self.store.path.read_bytes()
        self.assertEqual(self.store.configured_url(), 'http://127.0.0.1:9001')
        self.assertEqual(self.store.path.read_bytes(), protected)
        self.assertEqual(settings.read_bytes(), content)

    def test_invalid_plugin_port_is_not_used_as_a_connection_or_credential(self):
        settings = self.paths.obsidian_vault / '.obsidian/plugins/knowledge-orchestrator-bridge/data.json'
        settings.parent.mkdir(parents=True)
        for payload in ('{', '[]', 'null', json.dumps({'port': True}), json.dumps({'port': 0}),
                        json.dumps({'port': 65536}), json.dumps({'port': '8766'})):
            settings.write_text(payload, encoding='utf-8')
            self.assertEqual(self.store.configured_url(), 'http://127.0.0.1:8767')
            self.assertEqual(settings.read_text(encoding='utf-8'), payload)
            self.assertFalse(self.store.path.exists())

    def test_invalid_config_or_protection_failure_preserves_previous_configuration(self):
        self.store.save('http://127.0.0.1:8766', token=self.token)
        before = self.store.path.read_bytes()
        for url, token in [('http://remote.example:8766', self.token), ('http://127.0.0.1:8766', 'short')]:
            with self.assertRaises(ObsidianBridgeUnavailable):
                self.store.save(url, token=token)
            self.assertEqual(self.store.path.read_bytes(), before)
        with patch.object(self.store, '_protect', side_effect=OSError('private details')):
            with self.assertRaises(ObsidianBridgeUnavailable) as caught:
                self.store.save('http://127.0.0.1:9000', token=self.token)
        self.assertNotIn('private details', str(caught.exception))
        self.assertEqual(self.store.path.read_bytes(), before)

    def test_configuration_is_bound_to_vault_and_missing_or_corrupt_fails_closed(self):
        with self.assertRaises(ObsidianBridgeUnavailable):
            self.store.client()
        self.store.save('http://127.0.0.1:8766', token=self.token)
        other = ObsidianConnection(replace(self.paths, obsidian_vault=self.paths.state), unprotect=lambda b: b[::-1])
        with self.assertRaises(ObsidianBridgeUnavailable):
            other.client()
        for invalid in ('{', '{}', json.dumps({'url': 123, 'credential': 'value', 'vault_id': []})):
            self.store.path.write_text(invalid)
            with self.assertRaises(ObsidianBridgeUnavailable):
                self.store.client()

    @unittest.skipUnless(os.name == 'nt', 'DPAPI requiere Windows')
    def test_real_windows_protection_roundtrip(self):
        store = ObsidianConnection(self.paths)
        store.save('http://127.0.0.1:8766', token=self.token)
        self.assertEqual(store.client()._token, self.token)
        self.assertNotIn(self.token, store.path.read_text())
