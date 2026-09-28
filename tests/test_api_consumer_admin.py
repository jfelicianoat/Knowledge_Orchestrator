"""Consumidores de la API dados de alta desde la aplicación (hallazgo H19).

Antes solo existían los de KO_API_CLIENTS: dar acceso de lectura a otra
herramienta exigía salir del escritorio. Aquí se comprueba el circuito real
—listener de loopback incluido— y que la credencial no se guarda en claro.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import tkinter as tk
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.operations_status import OperationsStatusService

ENV_TOKEN = 'test-only-environment-credential-' + 'e' * 16


class ApiConsumerAdminTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.environment = patch.dict(os.environ, {'KO_API_CLIENTS': '[]'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.runtime = build_runtime(PipelinePaths.under(Path(self.temporary.name)))
        self.addCleanup(self.runtime.stop)
        self.consumers = self.runtime.api_server.consumers

    def get(self, address, path, token=None):
        headers = {'Authorization': 'Bearer ' + token} if token else {}
        with httpx.Client(timeout=3, trust_env=False) as client:
            return client.get(address + path, headers=headers)

    def post(self, address, path, token, body):
        with httpx.Client(timeout=3, trust_env=False) as client:
            return client.post(address + path, json=body, headers={
                'Authorization': 'Bearer ' + token, 'Idempotency-Key': 'consumer-test-0001'})

    def test_read_only_consumer_reads_but_cannot_ingest_or_approve_and_revocation_is_immediate(self):
        controller = self.runtime.api_server
        self.assertFalse(controller.snapshot()['configured'])
        with self.assertRaisesRegex(ValueError, 'consumidores'):
            controller.start(port=0)
        _, token = self.consumers.create('lector', ['read'])
        self.assertTrue(controller.snapshot()['configured'])
        address = controller.start(port=0)['address']
        self.assertEqual(self.get(address, '/status', token).status_code, 200)
        self.assertEqual(self.get(address, '/documents', token).status_code, 200)
        self.assertEqual(self.post(address, '/ingestions', token, {}).status_code, 403)
        self.assertEqual(self.post(address, '/review-tasks/1/approve', token, {}).status_code, 403)
        self.assertEqual(self.get(address, '/review-batches', token).status_code, 403)
        # Un consumidor creado con la API ya escuchando entra sin reiniciar.
        _, second = self.consumers.create('revisor', ['read', 'review'])
        self.assertEqual(self.get(address, '/review-batches', second).status_code, 200)
        self.assertTrue(self.consumers.revoke('lector'))
        self.assertEqual(self.get(address, '/status', token).status_code, 401)
        self.assertEqual(self.get(address, '/status', second).status_code, 200)
        self.assertEqual(controller.probe(second)['client'], 'revisor')
        self.assertEqual(controller.probe(token)['status'], 401)
        self.assertEqual(controller.probe()['status'], 401)

    def test_secret_is_stored_only_as_salted_hash_and_never_logged(self):
        _, token = self.consumers.create('lector', ['read'])
        _, other = self.consumers.create('otro', ['read'])
        self.assertNotEqual(token, other)
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            rows = [dict(row) for row in connection.execute('SELECT * FROM api_consumers')]
            dump = str(rows) + str([tuple(row) for row in connection.execute('SELECT * FROM events')])
        self.assertNotIn(token, dump)
        self.assertNotIn(token.encode(), b''.join(row['token_hash'] + row['token_salt'] for row in rows))
        self.assertNotEqual(rows[0]['token_salt'], rows[1]['token_salt'])
        status = json.dumps(OperationsStatusService(self.runtime).snapshot())
        self.assertNotIn(token, status)
        self.assertNotIn('token_hash', status)

    def test_validation_duplicates_and_environment_clients_are_merged(self):
        with self.assertRaisesRegex(ValueError, 'permiso'):
            self.consumers.create('sin-permisos', [])
        with self.assertRaisesRegex(ValueError, 'nombre'):
            self.consumers.create('con espacios', ['read'])
        with self.assertRaisesRegex(ValueError, 'Permiso'):
            self.consumers.create('raro', ['admin'])
        self.consumers.create('lector', ['read'])
        with self.assertRaisesRegex(ValueError, 'activo'):
            self.consumers.create('lector', ['read'])
        self.consumers.revoke('lector')
        self.consumers.create('lector', ['read'])  # revocado: el nombre queda libre
        clients = [{'name': 'externo', 'token': ENV_TOKEN, 'scopes': ['read']}]
        with patch.dict(os.environ, {'KO_API_CLIENTS': json.dumps(clients)}):
            controller = self.runtime.api_server
            with self.assertRaisesRegex(ValueError, 'fuera de la aplicación'):
                self.consumers.create('externo', ['read'], reserved_names=controller.environment_client_names())
            origins = {client['name']: client['origin'] for client in controller.snapshot()['clients']}
            self.assertEqual(origins, {'externo': 'environment', 'lector': 'application'})
            address = controller.start(port=0)['address']
            self.assertEqual(self.get(address, '/status', ENV_TOKEN).status_code, 200)
            controller.stop()


class ApiConsumerAdminUiTests(unittest.TestCase):
    def setUp(self):
        try:
            probe = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f'Tcl/Tk no disponible: {error}')
        probe.destroy()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.environment = patch.dict(os.environ, {'KO_API_CLIENTS': '[]'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.runtime = build_runtime(PipelinePaths.under(Path(self.temporary.name)))
        self.addCleanup(self.runtime.stop)
        from knowledge_orchestrator.ui.dashboard import OrchestratorDashboard
        self.window = OrchestratorDashboard(self.runtime)
        self.window.withdraw()
        self.addCleanup(self.window.destroy)
        self.window._startup = SimpleNamespace(done=True, error=None)

    def settle(self):
        deadline = time.monotonic() + 5
        while self.window._services_busy and time.monotonic() < deadline:
            self.window.update()
            time.sleep(0.01)
        self.window.update()

    def test_create_show_once_revoke_through_widgets(self):
        window = self.window
        window._show_page('services')
        self.settle()
        self.assertIn('Nuevo consumidor', window.api_hint_var.get())
        window._open_api_consumer_dialog()
        name_var, scope_vars = window._api_consumer_form
        self.assertTrue(scope_vars['read'].get())
        self.assertFalse(scope_vars['review'].get())
        with patch('knowledge_orchestrator.ui.dashboard.servicios.messagebox.showerror') as error:
            self.assertIsNone(window._create_api_consumer('mal nombre', ['read']))
            error.assert_called_once()
        token = window._create_api_consumer('lector', ['read'])
        self.assertIsNotNone(token)
        credential = window._api_credential_window
        entries = [child for frame in credential.winfo_children() for child in frame.winfo_children()
                   if child.winfo_class() == 'TEntry']
        self.assertEqual(entries[0].get(), token)
        window._api_credential_copy()
        self.assertEqual(window.clipboard_get(), token)
        credential.destroy()
        self.settle()
        tree = window.api_consumers_tree
        self.assertIn('lector', tree.get_children())
        self.assertEqual(tree.item('lector', 'values')[2], 'Aplicación')
        self.assertTrue(window.api_revoke_button.instate(['disabled']))
        tree.selection_set('lector')
        window.update()
        self.assertFalse(window.api_revoke_button.instate(['disabled']))
        with patch('knowledge_orchestrator.ui.dashboard.servicios.messagebox.askyesno', return_value=True):
            window._revoke_selected_api_consumer()
        self.settle()
        self.assertIsNone(self.runtime.api_server.consumers.authenticate(token or ''))
        # Sin actividad registrada, un consumidor revocado deja de listarse.
        self.assertNotIn('lector', tree.get_children())
        window._copy_api_example()
        self.assertIn('<TU_CREDENCIAL>', window.clipboard_get())
        self.assertNotIn(token or '', window.clipboard_get())

    def test_probe_reports_listener_and_credential(self):
        window = self.window
        _, token = self.runtime.api_server.consumers.create('lector', ['read'])
        self.assertIn('no responde', window._report_api_probe(self.runtime.api_server.probe(token), True))
        self.runtime.api_server.start(port=0)
        self.assertIn('«lector»', window._report_api_probe(self.runtime.api_server.probe(token), True))
        self.assertIn('exige credencial', window._report_api_probe(self.runtime.api_server.probe(), False))
        self.assertIn('no válida', window._report_api_probe(
            self.runtime.api_server.probe('ko_' + 'x' * 40), True))


if __name__ == '__main__':
    unittest.main()
