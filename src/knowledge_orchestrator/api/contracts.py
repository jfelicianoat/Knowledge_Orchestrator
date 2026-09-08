"""Schemas compartidos por validación HTTP y documentación OpenAPI."""
from __future__ import annotations

import math

from knowledge_orchestrator.domain.monitoring import ROLES

STATE = {'type': 'string', 'enum': ['current', 'historical', 'all'], 'default': 'current'}
PAGINATION = {
    'limit': {'type': 'integer', 'minimum': 1, 'maximum': 1000, 'default': 100},
    'offset': {'type': 'integer', 'minimum': 0, 'maximum': 1000000, 'default': 0},
}
QUERY = {
    'type': 'object', 'additionalProperties': False, 'required': ['question'],
    'properties': {'question': {'type': 'string', 'minLength': 1, 'maxLength': 4000}, 'state': STATE},
}
DOCUMENT = {
    'type': 'object', 'additionalProperties': False, 'required': ['title', 'content'],
    'properties': {'title': {'type': 'string', 'minLength': 1, 'maxLength': 500},
                   'content': {'type': 'string', 'minLength': 1, 'maxLength': 500000},
                   'source_url': {'type': 'string', 'minLength': 1, 'maxLength': 2000}},
}
SEMANTIC = {
    'type': 'object', 'additionalProperties': False, 'required': ['vector', 'model'],
    'properties': {'vector': {'type': 'array', 'minItems': 1, 'maxItems': 8192, 'items': {'type': 'number'}},
                   'model': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                   'state': STATE, 'limit': {**PAGINATION['limit'], 'default': 20}},
}
SOURCE: dict = {
    'type': 'object', 'additionalProperties': False, 'required': ['name', 'kind', 'location'],
    'properties': {
        'name': {'type': 'string', 'minLength': 1, 'maxLength': 200},
        'kind': {'type': 'string', 'enum': ['web', 'rss']},
        'location': {'type': 'string', 'minLength': 1, 'maxLength': 2000},
        'interval_seconds': {'type': 'integer', 'minimum': 60, 'maximum': 2592000},
        'enabled': {'type': 'boolean'}, 'scope': {'type': 'string', 'maxLength': 500},
        'trust_level': {'type': 'integer', 'minimum': 0, 'maximum': 100},
        'source_role': {'type': 'string', 'enum': list(ROLES)},
        'ingestion_policy': {'type': 'string', 'enum': ['review', 'ingest']},
        'credential_env': {'type': 'string', 'maxLength': 97},
    },
}
SOURCE_UPDATE = {**SOURCE, 'required': [*SOURCE['properties'], 'expected_revision'],
                 'properties': {**SOURCE['properties'], 'expected_revision': {'type': 'integer', 'minimum': 1}}}
REVIEW_ACTION = {
    'type': 'object', 'additionalProperties': False, 'required': ['expected_revision'],
    'properties': {'expected_revision': {'type': 'integer', 'minimum': 0},
                   'reason': {'type': 'string', 'minLength': 1, 'maxLength': 2000}},
}
REVIEW_BATCH_PREVIEW: dict = {
    'type': 'object', 'additionalProperties': False,
    'properties': {'selection': {'type': 'array', 'minItems': 1, 'maxItems': 1000, 'items': {
        'type': 'object', 'additionalProperties': False, 'required': ['candidate_id', 'expected_revision'],
        'properties': {'candidate_id': {'type': 'integer', 'minimum': 1},
                       'expected_revision': {'type': 'integer', 'minimum': 0}}}}},
}
REVIEW_BATCH_CONFIRM = {
    'type': 'object', 'additionalProperties': False, 'required': ['plan_hash'],
    'properties': {'plan_hash': {'type': 'string', 'minLength': 64, 'maxLength': 64}},
}
REVIEW_EDIT = {
    'type': 'object', 'additionalProperties': False,
    'required': ['expected_revision', 'relation', 'confidence', 'impact', 'rationale', 'replacement_text'],
    'properties': {
        'expected_revision': {'type': 'integer', 'minimum': 0},
        'relation': {'type': 'string', 'enum': ['SUPPORTS', 'EXTENDS', 'CONTRADICTS',
                                               'SUPERSEDES', 'UNRELATED', 'UNCERTAIN']},
        'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
        'impact': {'type': 'string', 'enum': ['LOW', 'MEDIUM', 'HIGH']},
        'rationale': {'type': 'string', 'minLength': 1, 'maxLength': 10000},
        'replacement_text': {'type': ['string', 'null'], 'maxLength': 500000},
    },
}
CLAIM_REVIEW = {
    'type': 'object', 'additionalProperties': False, 'required': ['expected_revision', 'state', 'reason'],
    'properties': {'expected_revision': {'type': 'integer', 'minimum': 1},
                   'state': {'type': 'string', 'enum': ['CURRENT', 'DISPUTED', 'UNCERTAIN', 'REVIEW_REQUIRED']},
                   'reason': {'type': 'string', 'minLength': 1, 'maxLength': 2000}},
}


def validate(value, schema: dict, field: str = 'body') -> None:
    kind = schema['type']
    if isinstance(kind, list):
        for alternative in kind:
            try:
                validate(value, {**schema, 'type': alternative}, field)
                return
            except ValueError:
                pass
        raise ValueError(f'{field}: tipo inválido')
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'string': isinstance(value, str), 'integer': type(value) is int,
             'number': type(value) in {int, float}, 'boolean': type(value) is bool, 'null': value is None}[kind]
    if not valid:
        raise ValueError(f'{field}: tipo inválido')
    if kind == 'null':
        return
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{field}: valor no permitido')
    if kind == 'object':
        if set(schema.get('required', [])) - set(value) or set(value) - set(schema['properties']):
            raise ValueError(f'{field}: campos ausentes o desconocidos')
        for key, child in value.items():
            validate(child, schema['properties'][key], field + '.' + key)
    elif kind == 'array':
        if not schema.get('minItems', 0) <= len(value) <= schema.get('maxItems', 10000):
            raise ValueError(f'{field}: tamaño fuera de límites')
        for child in value:
            validate(child, schema['items'], field + '[]')
    elif kind == 'string':
        if not schema.get('minLength', 0) <= len(value.strip()) <= schema.get('maxLength', 500000):
            raise ValueError(f'{field}: longitud fuera de límites')
    elif not math.isfinite(value) or not schema.get('minimum', -math.inf) <= value <= schema.get('maximum', math.inf):
        raise ValueError(f'{field}: número fuera de límites')
