from __future__ import annotations

import json
import os
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import asdict, replace
from unittest.mock import patch

import httpx

from knowledge_orchestrator.api.application import KnowledgeApi
from knowledge_orchestrator.api.auth import ApiAuth
from knowledge_orchestrator.api.openapi import ROUTES, specification
from knowledge_orchestrator.api.response_schemas import response_schema
from tests import test_automation_governance as governance

TOKEN = 'test-governance-administrator-token-001'
READER = 'test-governance-review-only-token-0002'
OTHER = 'test-governance-second-admin-token-003'


class AutomationGovernanceApiTests(unittest.TestCase):
    tearDown = governance.AutomationGovernanceTests.tearDown
    publish_monitored = governance.AutomationGovernanceTests.publish_monitored
    extraction = staticmethod(governance.AutomationGovernanceTests.extraction)
    prepared = governance.AutomationGovernanceTests.prepared

    def setUp(self):
        governance.AutomationGovernanceTests.setUp(self)
        auth = ApiAuth([{'name': 'governor', 'token': TOKEN, 'scopes': ['governance']},
                        {'name': 'reviewer', 'token': READER, 'scopes': ['read', 'review', 'sources']},
                        {'name': 'other-admin', 'token': OTHER, 'scopes': ['governance']}])
        self.client = httpx.Client(transport=httpx.WSGITransport(KnowledgeApi(self.runtime, auth)),
                                   base_url='http://localhost/api/v1/')
        self.addCleanup(self.client.close)

    def request(self, method, route, *, token=TOKEN, key='request-key-0001', **kwargs):
        return self.client.request(method, route, headers={'Authorization': 'Bearer ' + token,
                                                          'Idempotency-Key': key}, **kwargs)

    def simulate(self, policy, *, key='simulate-key-001', token=TOKEN):
        response = self.request('POST', f"automation/policies/{policy['policy_id']}/simulations", token=token,
                                key=key, json={'expected_revision': policy['revision']})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def activation(self, policy, simulation=None, *, enabled=True):
        return self.request('PATCH', f"automation/policies/{policy['policy_id']}/activation", json={
            'enabled': enabled, 'expected_revision': policy['revision'],
            'expected_state_revision': policy['state_revision'], 'reason': 'Reviewed sources and limits',
            **({'reviewed_simulation_id': simulation['simulation_id']} if simulation else {})})

    def control(self, paused, revision=1):
        return self.request('PATCH', 'automation/control', json={
            'paused': paused, 'expected_revision': revision, 'reason': 'Explicit test decision'})

    def assert_contract(self, data, schema):
        if '$ref' in schema:
            schema = specification()['components']['schemas'][schema['$ref'].rsplit('/', 1)[-1]]
        kinds = schema.get('type', [])
        kinds = [kinds] if isinstance(kinds, str) else kinds
        matches = {'object': isinstance(data, dict), 'array': isinstance(data, list), 'string': isinstance(data, str),
                   'integer': type(data) is int, 'boolean': type(data) is bool, 'null': data is None,
                   'number': type(data) in {int, float}}
        self.assertTrue(not kinds or any(matches[kind] for kind in kinds), (data, schema))
        if 'enum' in schema:
            self.assertIn(data, schema['enum'])
        if 'const' in schema:
            self.assertEqual(data, schema['const'])
        if isinstance(data, dict):
            self.assertFalse(set(schema.get('required', [])) - set(data), schema)
            for name, value in data.items():
                if name in schema.get('properties', {}):
                    self.assert_contract(value, schema['properties'][name])
                else:
                    self.assertNotEqual(schema.get('additionalProperties'), False)
        if isinstance(data, list) and 'items' in schema:
            for item in data:
                self.assert_contract(item, schema['items'])

    def test_every_governance_route_requires_dedicated_scope(self):
        for method, route, scope, *_ in ROUTES:
            if not route.startswith('/automation/'):
                continue
            self.assertEqual(scope, 'governance')
            path = route.replace('{policy_id}', '1').replace('{simulation_id}', 'a' * 32).replace('{run_id}', 'b' * 32)
            for token, status in (('', 401), (READER, 403)):
                with self.subTest(method=method, route=route, status=status):
                    response = self.request(method, path.lstrip('/'), token=token, json={})
                    self.assertEqual(response.status_code, status, response.text)
        self.assertTrue(self.runtime.automation_policies.control()['paused'])

    def test_creation_is_disabled_idempotent_and_actor_cannot_be_supplied(self):
        _, _, _, _, _, config = self.prepared()
        body = asdict(config)
        first = self.request('POST', 'automation/policies', json=body)
        self.assertEqual(first.status_code, 200, first.text)
        policy = first.json()
        self.assertFalse(policy['enabled'])
        self.assertEqual(policy['created_by'], 'api:governor')
        self.assert_contract(policy, response_schema('POST', '/automation/policies'))
        repeated = self.request('POST', 'automation/policies', json=body)
        self.assertEqual(repeated.json()['policy_id'], policy['policy_id'])
        changed = self.request('POST', 'automation/policies', json={**body, 'name': 'Different'})
        self.assertEqual(changed.status_code, 409)
        for field, value in (('actor', 'human:forged'), ('enabled', True), ('source_ids', []),
                             ('relations', ['CONTRADICTS']), ('max_tasks_per_day', 1)):
            response = self.request('POST', 'automation/policies', key='invalid-key-001', json={**body, field: value})
            self.assertEqual(response.status_code, 400, response.text)

    def test_simulation_is_frozen_idempotent_and_administrators_share_audit_visibility(self):
        old, _, _, repo, policy, config = self.prepared()
        before = old.vault_path.read_bytes()
        simulated = self.simulate(policy)
        self.assert_contract(simulated, response_schema('GET', '/automation/simulations/{simulation_id}'))
        self.assertEqual(simulated['plan']['counts']['eligible'], 1)
        second = self.simulate(policy, token=OTHER)
        self.assertNotEqual(second['simulation_id'], simulated['simulation_id'])
        repo.update(policy['policy_id'], replace(config, name='Revised'), expected_revision=1,
                    expected_state_revision=1, actor='human', reason='New version')
        self.assertEqual(self.simulate(policy), simulated)  # Replay does not recompute or reauthorize.
        changed = self.request('POST', f"automation/policies/{policy['policy_id']}/simulations",
                               key='simulate-key-001', json={'expected_revision': 2})
        self.assertEqual(changed.status_code, 409)
        fetched = self.request('GET', 'automation/simulations/' + simulated['simulation_id'], token=OTHER)
        self.assertEqual(fetched.json(), simulated)
        self.assertEqual(before, old.vault_path.read_bytes())

    def test_activation_requires_current_reviewed_simulation_and_preserves_audit_link(self):
        _, _, _, repo, policy, _ = self.prepared()
        self.assertEqual(self.activation(policy).status_code, 400)
        simulated = self.simulate(policy)
        enabled = self.activation(policy, simulated)
        self.assertEqual(enabled.status_code, 200, enabled.text)
        self.assertTrue(enabled.json()['enabled'])
        self.assertTrue(repo.control()['paused'])
        self.assertEqual(self.activation(policy, simulated).status_code, 409)
        history = self.request('GET', f"automation/policies/{policy['policy_id']}/history").json()
        self.assert_contract(history, response_schema('GET', '/automation/policies/{policy_id}/history'))
        decision = history['decisions'][0]
        self.assertEqual(decision['reviewed_simulation_id'], simulated['simulation_id'])
        self.assertEqual(decision['actor'], 'api:governor')
        disabled = self.activation(enabled.json(), enabled=False)
        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json()['enabled'])

    def test_foreign_or_old_control_simulation_cannot_authorize_policy(self):
        _, _, _, _, first, _ = self.prepared()
        first_sim = self.simulate(first)
        _, _, _, _, second, _ = self.prepared(label='Y', key='second-policy')
        self.assertEqual(self.activation(second, first_sim).status_code, 409)
        self.assertEqual(self.control(False).status_code, 200)
        self.assertEqual(self.activation(first, first_sim).status_code, 409)
        self.assertFalse(self.runtime.automation_policies.get(first['policy_id'])['enabled'])

    def test_edit_revokes_authorization_and_rejects_stale_revisions(self):
        _, _, _, _, policy, config = self.prepared()
        simulated = self.simulate(policy)
        enabled = self.activation(policy, simulated).json()
        path = f"automation/policies/{policy['policy_id']}"
        body = {'config': asdict(replace(config, min_confidence=0.97)), 'expected_revision': 1,
                 'expected_state_revision': enabled['state_revision'], 'reason': 'Raise confidence threshold'}
        changed = self.request('PATCH', path, json=body)
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertFalse(changed.json()['enabled'])
        self.assertEqual(changed.json()['revision'], 2)
        self.assertEqual(self.request('PATCH', path, json=body).status_code, 409)
        self.assertEqual(self.activation(changed.json(), simulated).status_code, 409)
        history = self.request('GET', path + '/history?limit=1&offset=1').json()
        self.assertEqual(history['versions'][0]['revision'], 1)

    def test_control_is_explicit_versioned_and_audited(self):
        self.assertEqual(self.request('GET', 'automation/control').json(), {'revision': 1, 'paused': True})
        for body in ({'paused': False}, {'paused': 0, 'expected_revision': 1, 'reason': 'x'},
                     {'paused': False, 'expected_revision': 1, 'reason': ' '}):
            self.assertEqual(self.request('PATCH', 'automation/control', json=body).status_code, 400)
        self.assertEqual(self.control(False).json(), {'revision': 2, 'paused': False})
        self.assertEqual(self.control(True).status_code, 409)
        self.assertEqual(self.control(True, 2).json(), {'revision': 3, 'paused': True})
        history = self.request('GET', 'automation/control/history?limit=2').json()
        self.assertEqual([row['paused'] for row in history['items']], [True, False])
        self.assert_contract(history, response_schema('GET', '/automation/control/history'))

    def test_api_authorized_scheduler_publishes_and_exposes_receipts_and_pagination(self):
        _, _, candidate, _, policy, _ = self.prepared()
        self.assertEqual(self.activation(policy, self.simulate(policy)).status_code, 200)
        self.control(False)
        scheduler = self.runtime.automation_scheduler
        scheduler.tick()
        scheduler.tick()
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate.candidate_id).status, 'APPLIED')
        for route in ('automation/policies', 'automation/simulations', 'automation/runs'):
            response = self.request('GET', route + '?limit=1')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(response.json()['items']), 1)
            self.assert_contract(response.json(), response_schema('GET', '/' + route))
        run = self.request('GET', 'automation/runs').json()['items'][0]
        receipt = self.request('GET', 'automation/runs/' + run['run_id']).json()
        self.assert_contract(receipt, response_schema('GET', '/automation/runs/{run_id}'))
        self.assertEqual(receipt['results'], {'APPLIED': 1})
        self.assertEqual(self.request('GET', 'automation/runs?policy_id=9999').json(), {'items': []})
        self.assertEqual(self.request('GET', 'automation/runs?offset=1').json(), {'items': []})
        schedule = self.request('GET', f"automation/policies/{policy['policy_id']}/schedule").json()
        self.assertEqual(schedule['schedule']['last_run_id'], run['run_id'])
        self.assertNotIn('lease_token', json.dumps(schedule))

    def test_idempotent_simulation_concurrency_and_transaction_failure(self):
        _, _, _, _, policy, _ = self.prepared()
        service = self.runtime.automation_governance
        def simulate():
            return service.simulate(policy['policy_id'], expected_revision=1, actor='ui', key='concurrent-001')
        with ThreadPoolExecutor(max_workers=2) as pool:
            simulations = list(pool.map(lambda _: simulate(), range(2)))
        self.assertEqual(simulations[0]['simulation_id'], simulations[1]['simulation_id'])
        with self.runtime.database.transaction() as connection:
            connection.execute('CREATE TRIGGER fail_simulation_request BEFORE INSERT ON automation_simulation_requests '
                               "BEGIN SELECT RAISE(ABORT,'simulated failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            service.simulate(policy['policy_id'], expected_revision=1, actor='ui', key='failure-0001')
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM automation_simulations').fetchone()[0], 1)

    def test_openapi_declares_scope_string_ids_and_activation_contract(self):
        spec = self.request('GET', 'openapi.json').json()
        for method, route, _scope, *_ in ROUTES:
            if route.startswith('/automation/'):
                operation = spec['paths'][route][method.lower()]
                self.assertEqual(operation['x-required-scope'], 'governance')
                self.assertNotEqual(operation['responses']['200']['content']['application/json']['schema'],
                                    {'type': 'object'})
        params = spec['paths']['/automation/runs/{run_id}']['get']['parameters']
        self.assertEqual(next(p for p in params if p['name'] == 'run_id')['schema']['type'], 'string')
        self.assertEqual(self.request('GET', 'automation/policies/invalid').status_code, 400)
        self.assertEqual(self.request('GET', 'automation/runs/missing').status_code, 404)

    def test_errors_and_request_events_do_not_expose_credentials_or_private_failures(self):
        with patch.object(self.runtime.automation_policies, 'control', side_effect=RuntimeError('private-detail')):
            response = self.request('GET', 'automation/control')
        self.assertEqual(response.status_code, 500)
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            events = str([tuple(row) for row in connection.execute('SELECT * FROM events')])
        for value in (TOKEN, READER, OTHER, 'private-detail'):
            self.assertNotIn(value, response.text + events)

    def test_real_loopback_pause_cancels_queued_intents_and_permissions_are_enforced(self):
        old, _, candidate, _, policy, _ = self.prepared()
        before = old.vault_path.read_bytes()
        self.activation(policy, self.simulate(policy))
        self.control(False)
        self.runtime.automation_scheduler.tick()
        clients = [{'name': 'governor', 'token': TOKEN, 'scopes': ['governance']},
                   {'name': 'reviewer', 'token': READER, 'scopes': ['review']}]
        controller = self.runtime.api_server
        with patch.dict(os.environ, {'KO_API_CLIENTS': json.dumps(clients)}):
            try:
                state = controller.start(port=0)
                with httpx.Client(trust_env=False, timeout=3) as client:
                    route = state['address'] + '/automation/control'
                    body = {'paused': True, 'expected_revision': 2, 'reason': 'Pause before publication'}
                    self.assertEqual(client.get(route).status_code, 401)
                    denied = client.patch(route, json=body, headers={'Authorization': 'Bearer ' + READER})
                    self.assertEqual(denied.status_code, 403)
                    paused = client.patch(route, json=body, headers={'Authorization': 'Bearer ' + TOKEN})
                    self.assertEqual(paused.status_code, 200, paused.text)
            finally:
                controller.stop()
        self.runtime.automation_scheduler.tick()
        self.assertEqual(old.vault_path.read_bytes(), before)
        current = self.runtime.semantic_repository.get_candidate(candidate.candidate_id)
        self.assertEqual(current.status, 'PENDING_REVIEW')
        run = self.request('GET', 'automation/runs').json()['items'][0]
        receipt = self.request('GET', 'automation/runs/' + run['run_id']).json()
        self.assertEqual(receipt['items'][0]['result']['reasons'], ['AUTOMATION_PAUSED'])
