"""Contratos de configuración y decisiones explícitas de gobernanza."""
from knowledge_orchestrator.api.contracts import REVIEW_BATCH_PREVIEW
from knowledge_orchestrator.domain.monitoring import ROLES

REVISION = {'type': 'integer', 'minimum': 1}
REASON = {'type': 'string', 'minLength': 1, 'maxLength': 2000}
IDENTIFIER = {'type': 'string', 'minLength': 32, 'maxLength': 32}


def choices(values: list[str]) -> dict:
    return {'type': 'array', 'minItems': 1, 'maxItems': 100, 'items': {'type': 'string', 'enum': values}}


POLICY: dict = {
    'type': 'object', 'additionalProperties': False, 'required': ['name', 'source_ids'],
    'properties': {
        'name': {'type': 'string', 'minLength': 1, 'maxLength': 200},
        'source_ids': {'type': 'array', 'minItems': 1, 'maxItems': 1000,
                       'items': {'type': 'integer', 'minimum': 1, 'maximum': 2**63 - 1}},
        'source_kinds': choices(['web', 'rss']), 'source_roles': choices(list(ROLES)),
        'relations': choices(['SUPERSEDES', 'EXTENDS']),
        'claim_types': {'type': 'array', 'minItems': 1, 'maxItems': 100,
                        'items': {'type': 'string', 'minLength': 1, 'maxLength': 64}},
        'min_source_trust': {'type': 'integer', 'minimum': 0, 'maximum': 100},
        'min_confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
        **{name: {'type': 'integer', 'minimum': 1, 'maximum': maximum} for name, maximum in (
            ('max_claims_per_task', 1000), ('max_notes_per_task', 1000),
            ('max_tasks_per_run', 1000), ('max_tasks_per_day', 10000))},
    },
}
POLICY_UPDATE = {
    'type': 'object', 'additionalProperties': False,
    'required': ['config', 'expected_revision', 'expected_state_revision', 'reason'],
    'properties': {'config': {**POLICY, 'required': list(POLICY['properties'])}, 'expected_revision': REVISION,
                   'expected_state_revision': REVISION, 'reason': REASON},
}
POLICY_ACTIVATION = {
    'type': 'object', 'additionalProperties': False,
    'required': ['enabled', 'expected_revision', 'expected_state_revision', 'reason'],
    'properties': {'enabled': {'type': 'boolean'}, 'expected_revision': REVISION,
                   'expected_state_revision': REVISION, 'reason': REASON, 'reviewed_simulation_id': IDENTIFIER},
}
AUTOMATION_CONTROL = {
    'type': 'object', 'additionalProperties': False, 'required': ['paused', 'expected_revision', 'reason'],
    'properties': {'paused': {'type': 'boolean'}, 'expected_revision': REVISION, 'reason': REASON},
}
POLICY_SIMULATION = {
    'type': 'object', 'additionalProperties': False, 'required': ['expected_revision'],
    'properties': {'expected_revision': REVISION, **REVIEW_BATCH_PREVIEW['properties']},
}
