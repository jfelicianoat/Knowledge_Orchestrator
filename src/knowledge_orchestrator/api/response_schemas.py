"""Contratos de respuesta para consumidores y herramientas OpenAPI."""
from __future__ import annotations

from knowledge_orchestrator.api.contracts import SOURCE


def ref(name: str) -> dict:
    return {'$ref': '#/components/schemas/' + name}


def page(item: dict) -> dict:
    return {'type': 'object', 'required': ['items'],
            'properties': {'items': {'type': 'array', 'items': item}}}


def object_schema(properties: dict, required: list[str]) -> dict:
    return {'type': 'object', 'required': required, 'properties': properties}


SCHEMAS = {
    'ProposalReview': object_schema({
        'candidate_id': {'type': 'integer'}, 'status': {'type': 'string'}, 'revision': {'type': 'integer'},
        'reviewed_by': {'type': ['string', 'null']}, 'applied_successor_id': {'type': ['integer', 'null']},
        'requires_regeneration': {'type': 'boolean'}, 'assessment': {'type': ['object', 'null']},
        'versions': {'type': 'array', 'items': object_schema({
            'candidate_id': {'type': 'integer'}, 'revision': {'type': 'integer'}, 'snapshot': {'type': 'object'},
            'actor': {'type': 'string'}, 'created_at': {'type': 'string'},
        }, ['candidate_id', 'revision', 'snapshot', 'actor', 'created_at'])},
    }, ['candidate_id', 'status', 'revision', 'requires_regeneration', 'assessment', 'versions']),
    'MonitoredSource': object_schema({
        'source_id': {'type': 'integer'}, 'revision': {'type': 'integer'}, 'config': SOURCE,
        'next_check_at': {'type': 'number'}, 'last_checked_at': {'type': ['number', 'null']},
        'last_changed_at': {'type': ['number', 'null']}, 'last_known_hash': {'type': ['string', 'null']},
        'last_error_code': {'type': ['string', 'null']}, 'failures': {'type': 'integer'},
        'check_id': {'type': ['string', 'null']}, 'lease_until': {'type': ['number', 'null']},
    }, ['source_id', 'revision', 'config', 'next_check_at', 'last_checked_at', 'last_error_code', 'failures']),
    'SourceCheck': object_schema({
        'check_id': {'type': 'string'}, 'source_id': {'type': 'integer'}, 'source_revision': {'type': 'integer'},
        'status': {'enum': ['RUNNING', 'CHANGED', 'UNCHANGED', 'ERROR', 'ABANDONED', 'SUPERSEDED']},
        'started_at': {'type': 'number'}, 'finished_at': {'type': ['number', 'null']},
        'error_code': {'type': ['string', 'null']},
    }, ['check_id', 'source_id', 'source_revision', 'status', 'started_at', 'finished_at', 'error_code']),
    'SourceChange': object_schema({
        'change_id': {'type': 'string'}, 'source_id': {'type': 'integer'}, 'source_revision': {'type': 'integer'},
        'title': {'type': 'string'}, 'content': {'type': 'string'}, 'source_url': {'type': 'string'},
        'previous_hash': {'type': ['string', 'null']}, 'content_hash': {'type': 'string'},
        'observed_at': {'type': 'number'}, 'status': {'enum': ['REVIEW', 'READY', 'DELIVERED']},
        'ingestion_id': {'type': ['string', 'null']}, 'provenance': {'type': 'object'},
        'delivery_error': {'type': ['string', 'null']},
    }, ['change_id', 'source_id', 'source_revision', 'title', 'status', 'observed_at', 'content_hash', 'ingestion_id']),
    'Evidence': object_schema({
        'evidence_id': {'type': 'integer'}, 'claim_id': {'type': 'integer'},
        'source_capture_id': {'type': 'string'}, 'quote': {'type': 'string'},
        'span_start': {'type': 'integer'}, 'span_end': {'type': 'integer'},
    }, ['evidence_id', 'claim_id', 'source_capture_id', 'quote', 'span_start', 'span_end']),
    'Source': object_schema({
        'capture_id': {'type': 'string'}, 'title': {'type': 'string'}, 'source_type': {'type': 'string'},
        'source_origin': {'type': 'string'}, 'source_url': {'type': 'string'},
    }, ['capture_id', 'title', 'source_type', 'source_origin']),
    'Entity': object_schema({'entity_id': {'type': 'integer'}, 'name': {'type': 'string'},
                             'entity_key': {'type': 'string'}}, ['entity_id', 'name', 'entity_key']),
    'Claim': object_schema({
        'claim_id': {'type': 'integer'}, 'note_id': {'type': 'integer'}, 'statement': {'type': 'string'},
        'status': {'type': 'string', 'enum': ['CURRENT', 'HISTORICAL', 'SUPERSEDED', 'DISPUTED',
                                            'UNCERTAIN', 'REVIEW_REQUIRED']},
        'knowledge_state': {'type': 'string'}, 'revision': {'type': 'integer'},
        'valid_from': {'type': ['string', 'null']}, 'valid_until': {'type': ['string', 'null']},
        'manual_lock': {'type': 'boolean'}, 'superseded_by': {'type': ['integer', 'null']},
        'supersedes': {'type': 'array', 'items': {'type': 'integer'}},
        'entity_ids': {'type': 'array', 'items': {'type': 'integer'}},
        'evidence': {'type': 'array', 'items': ref('Evidence')}, 'sources': {'type': 'array', 'items': ref('Source')},
        'verification': {'const': 'evidence_linked_not_independently_verified'},
    }, ['claim_id', 'note_id', 'statement', 'status', 'knowledge_state', 'revision',
        'entity_ids', 'evidence', 'sources']),
    'Document': object_schema({
        'document_id': {'type': 'integer'}, 'title': {'type': 'string'}, 'revision': {'type': 'integer'},
        'content_hash': {'type': 'string'}, 'content': {'type': 'string'}, 'format': {'const': 'markdown'},
        'knowledge_state': {'const': 'mixed_document'}, 'source': ref('Source'),
    }, ['document_id', 'title', 'revision', 'content_hash', 'content', 'knowledge_state', 'source']),
    'Ingestion': object_schema({
        'ingestion_id': {'type': 'string'}, 'capture_id': {'type': 'string'},
        'status': {'enum': ['PENDING', 'DELIVERED', 'CONFLICT']},
        'capture_status': {'type': ['string', 'null']}, 'created_at': {'type': 'string'},
    }, ['ingestion_id', 'capture_id', 'status', 'capture_status', 'created_at']),
    'Query': object_schema({
        'query_id': {'type': 'string'}, 'status': {'enum': ['READY', 'SUBMITTING', 'QUEUED', 'PROCESSING',
                                                        'SUCCESS', 'ERROR', 'STALE']},
        'knowledge_state': {'enum': ['current', 'historical', 'all']},
        'created_at': {'type': 'string'},
        'answer': {'type': 'string'}, 'answer_mode': {'const': 'evidence_quotes'},
        'claims': {'type': 'array', 'items': ref('Claim')},
        'evidence': {'type': 'array', 'items': ref('Evidence')},
        'sources': {'type': 'array', 'items': ref('Source')},
        'insufficient_evidence': {'type': 'boolean'}, 'uncertainties': {'type': 'array', 'items': {'type': 'string'}},
        'generated_at': {'type': 'string'}, 'error_code': {'type': ['string', 'null']},
    }, ['query_id', 'status', 'knowledge_state', 'created_at', 'error_code']),
}


def response_schema(method: str, path: str) -> dict:
    if path.startswith('/review-tasks/') and method in {'POST', 'PATCH'}:
        return ref('ProposalReview')
    if path == '/sources':
        return page(ref('MonitoredSource')) if method == 'GET' else ref('MonitoredSource')
    if path in {'/sources/{source_id}', '/sources/{source_id}/check'}:
        return ref('MonitoredSource')
    if path == '/sources/{source_id}/checks':
        return page(ref('SourceCheck'))
    if path == '/source-changes':
        return page(ref('SourceChange'))
    if path.startswith('/source-changes/'):
        return ref('SourceChange')
    if path in {'/query', '/queries/{query_id}'}:
        return ref('Query')
    if path.startswith('/ingestions') or (path == '/documents' and method == 'POST'):
        return ref('Ingestion')
    if path in {'/claims', '/search'}:
        return page(ref('Claim'))
    if path == '/entities':
        return page(ref('Entity'))
    if path == '/entities/{entity_id}':
        return ref('Entity')
    if path in {'/claims/{claim_id}', '/claims/{claim_id}/knowledge-state'}:
        return ref('Claim')
    if path == '/documents/{document_id}':
        return ref('Document')
    if path == '/search/semantic':
        return page(object_schema({'score': {'type': 'number'}, 'claim': ref('Claim')}, ['score', 'claim']))
    return {'type': 'object'}
