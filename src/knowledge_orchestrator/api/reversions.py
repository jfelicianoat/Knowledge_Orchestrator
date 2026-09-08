"""Reversión humana con permiso review y planes privados del consumidor que los solicita."""
from __future__ import annotations

from knowledge_orchestrator.api.contracts import PAGINATION
from knowledge_orchestrator.services.reversion_view import reversion_view

REVISION = {'type': 'integer', 'minimum': 1, 'maximum': 2**63 - 1}
PREVIEW = {'type': 'object', 'additionalProperties': False, 'required': ['candidate_id', 'expected_revision'],
           'properties': {'candidate_id': REVISION, 'expected_revision': REVISION}}
CONFIRM = {'type': 'object', 'additionalProperties': False, 'required': ['expected_plan_hash', 'reason'],
           'properties': {'expected_plan_hash': {'type': 'string', 'minLength': 64, 'maxLength': 64},
                          'reason': {'type': 'string', 'minLength': 1, 'maxLength': 2000}}}
ROUTES = [
    ('GET', '/review-publications', 'review', 'Publicaciones aplicadas y estado de compensación', None, PAGINATION),
    ('GET', '/review-reversions', 'review', 'Planes y recibos propios de reversión', None,
     {**PAGINATION, 'candidate_id': REVISION}),
    ('POST', '/review-reversions/preview', 'review', 'Preparar reversión sin modificar conocimiento', PREVIEW, {}),
    ('GET', '/review-reversions/{reversion_id}', 'review', 'Vista previa y recibo propios de reversión', None, {}),
    ('POST', '/review-reversions/{reversion_id}/confirm', 'review', 'Confirmar reversión con hash revisado y motivo',
     CONFIRM, {}),
]


def dispatch(runtime, method, route, ids, query, body, owner, key):
    service = runtime.maintenance_reversion
    actor = 'api:' + owner
    if route == '/review-publications':
        return 200, {'items': service.repository.publications(**query)}, {}
    if route == '/review-reversions':
        return 200, {'items': service.repository.list_records(actor=actor, **query)}, {}
    if route == '/review-reversions/preview':
        record = service.preview(actor=actor, key=key, **body)
        return 200, reversion_view(record), {'Location': '/api/v1/review-reversions/' + record['reversion_id']}
    try:
        record = service.repository.get(ids['reversion_id'], actor=actor)
    except ValueError as error:
        raise LookupError('Reversión no disponible') from error
    if method == 'POST':
        record = service.confirm(ids['reversion_id'], actor=actor, **body)
    return 200, reversion_view(record), {}


def response_schema(method: str, path: str) -> dict:
    item: dict
    properties = {'reversion_id': {'type': 'string'}, 'candidate_id': {'type': 'integer'},
                  'owner': {'type': 'string'}, 'plan_hash': {'type': 'string'},
                  'status': {'enum': ['PREVIEW', 'APPLYING', 'APPLIED', 'CONFLICT']},
                  **{key: {'type': ['string', 'null']} for key in (
                      'reason', 'error_code', 'confirmed_at', 'finished_at')}, 'created_at': {'type': 'string'}}
    if path == '/review-publications':
        item = {'type': 'object', 'required': ['candidate_id', 'proposal_revision', 'note_id', 'title',
                                               'applied_at', 'reviewed_by', 'reversion_status'],
                'properties': {**{key: {'type': 'integer'} for key in (
                    'candidate_id', 'proposal_revision', 'note_id')}, 'title': {'type': 'string'},
                    'applied_at': {'type': 'string'}, 'reviewed_by': {'type': ['string', 'null']},
                    'reversion_status': {'enum': [None, 'APPLYING', 'APPLIED']},
                    'automation_run_id': {'type': ['string', 'null']}, 'review_batch_id': {'type': ['string', 'null']}}}
    else:
        item = {'type': 'object', 'required': list(properties), 'properties': properties, 'additionalProperties': False}
    if path in {'/review-publications', '/review-reversions'}:
        return {'type': 'object', 'required': ['items'],
                'properties': {'items': {'type': 'array', 'items': item}}, 'additionalProperties': False}
    plan = {**{key: {'type': 'integer'} for key in (
        'note_id', 'target_claim_id', 'successor_claim_id', 'proposal_revision')},
            **{key: {'type': 'string'} for key in ('base_hash', 'result_hash', 'before', 'proposed')},
            'restore_state': {'enum': ['CURRENT', 'DISPUTED', 'UNCERTAIN', 'REVIEW_REQUIRED']},
            'publication_authorized': {'const': False},
            'evidence': {'type': 'array', 'items': {'$ref': '#/components/schemas/Evidence'}}}
    properties['plan'] = {'type': 'object', 'properties': plan, 'required': list(plan), 'additionalProperties': False}
    item['required'].append('plan')
    return item
