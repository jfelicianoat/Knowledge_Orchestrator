from __future__ import annotations

import json
import os
import socket
import tempfile
import unittest
from unittest.mock import patch

import httpx

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.operations_status import OperationsStatusService


class OperationsStatusTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        from pathlib import Path
        self.runtime = build_runtime(PipelinePaths.under(Path(self.temporary.name)))
        self.addCleanup(self.runtime.stop)
        self.environment = patch.dict(os.environ, {'KO_API_CLIENTS': json.dumps([
            {'name': 'reader', 'scopes': ['read'], 'token': 'test-only-credential-' + 'a' * 32},
            {'name': 'reviewer', 'scopes': ['review'], 'token': 'test-only-credential-' + 'b' * 32}])})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_status_is_stopped_until_actual_listener_and_does_not_expose_secrets(self):
        service = OperationsStatusService(self.runtime)
        status = service.snapshot()
        self.assertEqual(status['api']['state'], 'STOPPED')
        self.assertFalse(status['api']['running'])
        self.assertIsNone(status['api']['address'])
        self.assertTrue(status['api']['configured'])
        self.assertEqual(status['consumers'][0]['scopes'], ['read'])
        self.assertNotIn('test-only-credential', json.dumps(status))
        self.assertNotIn('token_hash', json.dumps(status))
        self.assertFalse(status['autoapproval']['enabled'])
        self.assertEqual(status['workers'], {'broker': False, 'reviews': False, 'sources': False,
                                             'automations': False})

    def test_real_loopback_start_stop_restart_and_scopes(self):
        controller = self.runtime.api_server
        snapshot = controller.start(port=0)
        self.assertTrue(snapshot['running'])
        address = snapshot['address']
        self.assertEqual(controller.start(port=0)['address'], address)
        with httpx.Client(timeout=3, trust_env=False) as client:
            self.assertEqual(client.get(address + '/status').status_code, 401)
            headers = {'Authorization': 'Bearer test-only-credential-' + 'a' * 32}
            self.assertEqual(client.get(address + '/status', headers=headers).status_code, 200)
            self.assertEqual(client.get(address + '/review-batches', headers=headers).status_code, 403)
            observed = OperationsStatusService(self.runtime).snapshot()
            self.assertEqual(observed['consumers'][0]['requests'], 2)
            self.assertEqual(observed['consumers'][0]['errors'], 1)
        controller.stop()
        self.assertFalse(controller.snapshot()['running'])
        with httpx.Client(timeout=1, trust_env=False) as client, \
                self.assertRaises((httpx.ConnectError, httpx.ConnectTimeout)):
            client.get(address + '/status')
        restarted = controller.start(port=0)
        self.assertTrue(restarted['running'])
        self.runtime.stop()
        self.assertEqual(controller.snapshot()['state'], 'STOPPED')

    def test_credentials_are_frozen_while_listening_and_reload_on_restart(self):
        controller = self.runtime.api_server
        address = controller.start(port=0)['address']
        with patch.dict(os.environ, {'KO_API_CLIENTS': '[]'}):
            self.assertTrue(controller.snapshot()['configured'])
            with httpx.Client(timeout=3, trust_env=False) as client:
                self.assertEqual(client.get(address + '/status', headers={
                    'Authorization': 'Bearer test-only-credential-' + 'a' * 32}).status_code, 200)
            controller.stop()
            self.assertFalse(controller.snapshot()['configured'])
            with self.assertRaisesRegex(ValueError, 'consumidores'):
                controller.start(port=0)
            self.assertEqual(controller.snapshot()['error_code'], 'API_CREDENTIALS_NOT_CONFIGURED')

    def test_busy_port_and_invalid_configuration_are_reported_without_false_running(self):
        controller = self.runtime.api_server
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            with self.assertRaisesRegex(ValueError, 'puerto'):
                controller.start(port=occupied.getsockname()[1])
        self.assertEqual(controller.snapshot()['error_code'], 'API_BIND_FAILED')
        self.assertFalse(controller.snapshot()['running'])
        with self.assertRaises(ValueError):
            controller.start(port=-1)
        with patch.dict(os.environ, {'KO_API_CLIENTS': 'not-json-sensitive-test-value'}):
            with self.assertRaises(ValueError) as error:
                controller.start(port=0)
            self.assertNotIn('not-json-sensitive-test-value', str(error.exception))

    def test_activity_is_bounded_and_does_not_expose_request_bodies(self):
        with self.runtime.database.transaction() as connection:
            for _index in range(1003):
                details = {'client': 'former', 'route': '/claims', 'method': 'GET', 'status': 200,
                           'token': 'must-not-be-shown', 'body': 'sensitive request text'}
                connection.execute('INSERT INTO events(event_type,message,details_json) VALUES (?,?,?)',
                                   ('API_REQUEST', 'message not displayed', json.dumps(details)))
            connection.execute("INSERT INTO events(event_type,message,details_json) VALUES ('API_REQUEST','bad','{')")
        snapshot = OperationsStatusService(self.runtime).snapshot()
        self.assertEqual(len(snapshot['activity']), 1000)
        former = next(c for c in snapshot['consumers'] if c['name'] == 'former')
        self.assertFalse(former['configured'])
        self.assertEqual(former['requests'], 1000)
        self.assertEqual(former['scopes'], [])
        self.assertNotIn('must-not-be-shown', json.dumps(snapshot))
        self.assertNotIn('sensitive request text', json.dumps(snapshot))
        self.assertGreater(snapshot['activity'][0]['event_id'], snapshot['activity'][-1]['event_id'])

    def test_request_telemetry_does_not_echo_unmatched_urls_or_arbitrary_methods(self):
        self.runtime.repository.record_event('API_REQUEST', 'request', details={
            'client': 'user?token=private', 'route': '/not-a-route?key=private',
            'method': 'arbitrary-private-input', 'status': 'private'})
        snapshot = OperationsStatusService(self.runtime).snapshot()
        self.assertNotIn('private', json.dumps(snapshot))
        self.assertEqual(snapshot['activity'][0]['route'], 'unmatched')
        self.assertIsNone(snapshot['activity'][0]['client'])
