from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

import httpx

from knowledge_orchestrator.api.application import KnowledgeApi
from knowledge_orchestrator.api.auth import ApiAuth
from knowledge_orchestrator.api.openapi import specification
from knowledge_orchestrator.api.response_schemas import response_schema
from knowledge_orchestrator.api.reversions import ROUTES
from tests import test_automation_governance_api as governance_api
from tests import test_maintenance_reversion as reversion

TOKEN = 'test-reversion-reviewer-token-00001'
OTHER = 'test-reversion-second-token-000002'
READER = 'test-reversion-reader-token-000003'


class ReversionApiTests(unittest.TestCase):
    tearDown = reversion.MaintenanceReversionTests.tearDown
    publish_monitored = reversion.MaintenanceReversionTests.publish_monitored
    extraction = staticmethod(reversion.MaintenanceReversionTests.extraction)
    prepared = reversion.MaintenanceReversionTests.prepared
    simulation = reversion.MaintenanceReversionTests.simulation
    authorize = reversion.MaintenanceReversionTests.authorize
    queue = reversion.MaintenanceReversionTests.queue
    applied = reversion.MaintenanceReversionTests.applied
    assert_contract = governance_api.AutomationGovernanceApiTests.assert_contract

    def setUp(self):
        reversion.MaintenanceReversionTests.setUp(self)
        self.auth = [{'name': 'reviewer', 'token': TOKEN, 'scopes': ['review', 'read']},
                     {'name': 'other', 'token': OTHER, 'scopes': ['review']},
                     {'name': 'reader', 'token': READER, 'scopes': ['read', 'governance']}]
        self.client = httpx.Client(transport=httpx.WSGITransport(KnowledgeApi(self.runtime, ApiAuth(self.auth))),
                                   base_url='http://localhost/api/v1/')
        self.addCleanup(self.client.close)

    def request(self, method, route, *, token=TOKEN, key='reversion-api-key-001', **kwargs):
        return self.client.request(method, route, headers={'Authorization': 'Bearer ' + token,
                                                          'Idempotency-Key': key}, **kwargs)

    def preview(self, candidate, *, key='reversion-api-key-001'):
        response = self.request('POST', 'review-reversions/preview', key=key, json={
            'candidate_id': candidate.candidate_id, 'expected_revision': candidate.proposal_revision})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['Location'], '/api/v1/review-reversions/' + response.json()['reversion_id'])
        return response.json()

    def confirm(self, plan, **kwargs):
        return self.request('POST', f"review-reversions/{plan['reversion_id']}/confirm", json={
            'expected_plan_hash': plan['plan_hash'], 'reason': 'Reversión revisada expresamente', **kwargs})

    def test_routes_require_review_and_document_contracts_without_granting_governance_publication(self):
        for method, route, scope, *_ in ROUTES:
            self.assertEqual(scope, 'review')
            route = route.replace('{reversion_id}', 'a' * 36).lstrip('/')
            for token, expected in (('', 401), (READER, 403)):
                with self.subTest(route=route, token=bool(token)):
                    response = self.request(method, route, token=token, json={})
                    self.assertEqual(response.status_code, expected)
        schema = specification()['paths']['/review-reversions/{reversion_id}']['get']
        identifier = next(p for p in schema['parameters'] if p['name'] == 'reversion_id')
        self.assertEqual(identifier['schema']['type'], 'string')

    def test_preview_is_frozen_scoped_idempotent_and_excludes_internal_paths(self):
        old, _, candidate, _, _ = self.applied()
        before = old.vault_path.read_bytes()
        plan = self.preview(candidate)
        self.assertEqual(self.preview(candidate), plan)
        self.assertEqual(plan['owner'], 'api:reviewer')
        self.assertEqual(plan['status'], 'PREVIEW')
        self.assertFalse(plan['plan']['publication_authorized'])
        self.assertEqual(old.vault_path.read_bytes(), before)
        self.assertNotIn('notes', plan['plan'])
        self.assertNotIn('claims', plan['plan'])
        self.assertNotIn('patch', plan['plan'])
        for evidence in plan['plan']['evidence']:
            self.assertNotIn('source_path', evidence)
        self.assert_contract(plan, response_schema('POST', '/review-reversions/preview'))
        url = 'review-reversions/' + plan['reversion_id']
        self.assertEqual(self.request('GET', url).json(), plan)
        self.assertEqual(self.request('GET', url, token=OTHER).status_code, 404)
        denied = self.request('POST', url + '/confirm', token=OTHER,
                              json={'expected_plan_hash': plan['plan_hash'], 'reason': 'Other'})
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(self.request('GET', 'review-reversions', token=OTHER).json()['items'], [])

    def test_confirmation_and_repeat_preserve_current_history_and_publication_receipt(self):
        old, _, candidate, before, _ = self.applied()
        plan = self.preview(candidate)
        response = self.confirm(plan)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['status'], 'APPLIED')
        self.assertEqual(self.confirm(plan).json(), response.json())
        self.assert_contract(response.json(), response_schema('POST', '/review-reversions/{reversion_id}/confirm'))
        self.assertEqual(old.vault_path.read_text(encoding='utf-8'), before)
        current = self.request('GET', f'claims?note_id={old.note_id}').json()['items']
        self.assertEqual([claim['claim_id'] for claim in current], [candidate.target_claim_id])
        history = self.request('GET', f'claims/{candidate.target_claim_id}/history').json()
        self.assertEqual([row['to_state'] for row in history['transitions']], ['CURRENT', 'SUPERSEDED', 'CURRENT'])
        publications = self.request('GET', 'review-publications').json()
        self.assertEqual(publications['items'][0]['reversion_status'], 'APPLIED')
        self.assert_contract(publications, response_schema('GET', '/review-publications'))
        self.assertEqual(self.confirm(plan, reason='Otro motivo').status_code, 409)

    def test_invalid_or_stale_confirmation_never_modifies_document(self):
        old, _, candidate, _, _ = self.applied()
        plan = self.preview(candidate)
        published = old.vault_path.read_bytes()
        for fields, status in (({'expected_plan_hash': 'a' * 64}, 409), ({'reason': ' '}, 400),
                                ({'actor': 'fake'}, 400), ({'expected_plan_hash': True}, 400)):
            with self.subTest(fields=fields):
                self.assertEqual(self.confirm(plan, **fields).status_code, status)
        old.vault_path.write_bytes(published + b'\nExternal edit')
        self.assertEqual(self.confirm(plan).status_code, 409)
        self.assertEqual(old.vault_path.read_bytes(), published + b'\nExternal edit')

    def test_paging_filters_and_invalid_request_shapes(self):
        _, _, candidate, _, _ = self.applied()
        self.preview(candidate)
        self.preview(candidate, key='reversion-api-key-002')
        for route in ('review-publications?limit=1&offset=0',
                       f'review-reversions?candidate_id={candidate.candidate_id}&limit=1&offset=1'):
            response = self.request('GET', route)
            self.assertEqual(len(response.json()['items']), 1)
            self.assert_contract(response.json(), response_schema('GET', '/' + route.split('?')[0]))
        self.assertEqual(self.request('GET', 'review-reversions?candidate_id=999999').json()['items'], [])
        for route in ('review-reversions?limit=0', 'review-reversions?owner=other', 'review-publications?offset=-1'):
            self.assertEqual(self.request('GET', route).status_code, 400)
        for body in ({'candidate_id': True, 'expected_revision': 1},
                     {'candidate_id': candidate.candidate_id, 'expected_revision': 1, 'actor': 'fake'}):
            self.assertEqual(self.request('POST', 'review-reversions/preview', json=body).status_code, 400)

    def test_failure_after_commit_is_observable_and_retry_does_not_duplicate(self):
        _, _, candidate, _, _ = self.applied()
        plan = self.preview(candidate)
        repo = self.runtime.maintenance_reversion.repository
        original = repo.finish
        def finish_then_lose_response(identifier):
            original(identifier)
            raise RuntimeError('private internal details')
        with patch.object(repo, 'finish', side_effect=finish_then_lose_response):
            response = self.confirm(plan)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('private internal', response.text)
        receipt = self.request('GET', 'review-reversions/' + plan['reversion_id']).json()
        self.assertEqual(receipt['status'], 'APPLIED')
        self.assertEqual(self.confirm(plan).json(), receipt)

    def test_real_loopback_confirmation_requires_auth_and_restores_only_fixture_note(self):
        old, _, candidate, before, _ = self.applied()
        with patch.dict(os.environ, {'KO_API_CLIENTS': json.dumps(self.auth)}):
            state = self.runtime.api_server.start(port=0)
        self.addCleanup(self.runtime.api_server.stop)
        with httpx.Client(base_url=state['address'] + '/', trust_env=False, timeout=10) as client:
            self.assertEqual(client.get('review-publications').status_code, 401)
            headers = {'Authorization': 'Bearer ' + TOKEN, 'Idempotency-Key': 'loopback-reversion-001'}
            response = client.post('review-reversions/preview', headers=headers,
                                   json={'candidate_id': candidate.candidate_id,
                                         'expected_revision': candidate.proposal_revision})
            self.assertEqual(response.status_code, 200, response.text)
            plan = response.json()
            response = client.post(f"review-reversions/{plan['reversion_id']}/confirm", headers=headers,
                                   json={'expected_plan_hash': plan['plan_hash'], 'reason': 'Revisión HTTP local'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['status'], 'APPLIED')
        self.assertEqual(old.vault_path.read_text(encoding='utf-8'), before)
