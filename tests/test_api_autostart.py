"""La API se inicia sola al abrir la aplicación (uso real 19-oct: ChatyGPT no podía consultar
porque nadie había pulsado «Iniciar API»)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from knowledge_orchestrator.config import BrokerSettings, PipelinePaths
from knowledge_orchestrator.runtime import build_runtime


class ApiAutostartTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        environment = patch.dict(os.environ, {'KO_API_CLIENTS': '[]'})
        environment.start()
        self.addCleanup(environment.stop)
        self.runtime = build_runtime(
            PipelinePaths.under(Path(temporary.name)), broker_settings=BrokerSettings(base_url='http://127.0.0.1:9'),
        )
        self.addCleanup(self.runtime.stop)
        self.controller = self.runtime.api_server

    def test_defaults_to_autostart_without_a_remembered_port(self):
        self.assertEqual(self.controller.preferences(), {'autostart': True, 'port': None})

    def test_without_consumers_nothing_starts(self):
        self.assertIsNone(self.controller.autostart(0))
        self.assertFalse(self.controller.snapshot()['running'])

    def test_with_a_consumer_the_api_starts_and_answers(self):
        _consumer, token = self.controller.consumers.create('ChatyGPT', ['read'])

        snapshot = self.controller.autostart(0)

        assert snapshot is not None
        self.assertTrue(snapshot['running'])
        with httpx.Client(timeout=3, trust_env=False) as client:
            response = client.get(snapshot['address'] + '/status', headers={'Authorization': 'Bearer ' + token})
        self.assertEqual(response.status_code, 200)

    def test_unchecked_preference_is_respected_and_persisted(self):
        self.controller.consumers.create('ChatyGPT', ['read'])
        self.controller.save_preferences(autostart=False, port=8799)

        self.assertIsNone(self.controller.autostart(0))
        self.assertFalse(self.controller.snapshot()['running'])
        self.assertEqual(self.controller.preferences(), {'autostart': False, 'port': 8799})

    def test_corrupt_preferences_fall_back_to_defaults(self):
        path = self.runtime.paths.state / 'api_settings.json'
        path.write_text('{"autostart": "sí", "port": 99999}', encoding='utf-8')
        self.assertEqual(self.controller.preferences(), {'autostart': True, 'port': None})


if __name__ == '__main__':
    unittest.main()
