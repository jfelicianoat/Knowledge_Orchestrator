"""Respuestas de gobernanza con versiones, recibos y planes auditables."""
from knowledge_orchestrator.api.automation_contracts import POLICY

INTEGER = {'type': 'integer'}
STRING = {'type': 'string'}
NULL_STRING = {'type': ['string', 'null']}
BOOLEAN = {'type': 'boolean'}


def record(fields: dict) -> dict:
    return {'type': 'object', 'required': list(fields), 'properties': fields}


def array(item: dict) -> dict:
    return {'type': 'array', 'items': item}


def page(item: dict) -> dict:
    return record({'items': array(item)})


def ref(name: str) -> dict:
    return {'$ref': '#/components/schemas/' + name}


POLICY_FIELDS = {'policy_id': INTEGER, 'revision': INTEGER, 'state_revision': INTEGER,
                 'enabled': BOOLEAN, 'approved_by': NULL_STRING}
SIMULATION_FIELDS = {'simulation_id': STRING, 'policy_id': INTEGER, 'policy_revision': INTEGER,
                     'policy_state_revision': INTEGER, 'control_revision': INTEGER,
                     'actor': STRING, 'created_at': STRING}
RUN_FIELDS = {'run_id': STRING, 'simulation_id': STRING, 'policy_id': INTEGER, 'policy_revision': INTEGER,
              'policy_state_revision': INTEGER, 'control_revision': INTEGER, 'status': {
                  'type': 'string', 'enum': ['READY', 'RUNNING', 'RECOVERY_REQUIRED', 'COMPLETE']},
              'created_at': STRING, 'completed_at': NULL_STRING}
CONTROL_FIELDS = {'revision': INTEGER, 'paused': BOOLEAN}
SCHEMAS = {
    'AutomationPolicy': record({**POLICY_FIELDS, 'config': POLICY, 'approved_at': NULL_STRING,
                                 'created_by': STRING, 'created_at': STRING}),
    'AutomationPolicySummary': record({**POLICY_FIELDS, 'name': STRING}),
    'AutomationSimulationSummary': record(SIMULATION_FIELDS),
    'AutomationSimulation': record({**SIMULATION_FIELDS, 'plan': record({
        'mode': {'type': 'string', 'const': 'dry_run'},
        'publication_authorized': {'type': 'boolean', 'const': False},
        'limits_reserved': {'type': 'boolean', 'const': False},
        'execution_gates': array(STRING), 'counts': record({'tasks': INTEGER, 'eligible': INTEGER}),
        'daily_usage': INTEGER, 'daily_remaining': INTEGER, 'quota_timezone': {'type': 'string', 'const': 'UTC'},
        'daily_quota_evaluated': BOOLEAN, 'policy': {'type': 'object'},
        'items': array(record({'candidate_id': INTEGER, 'revision': INTEGER, 'eligible': BOOLEAN,
                               'blockers': array(STRING)})),
    })}),
    'AutomationRunSummary': record(RUN_FIELDS),
    'AutomationRun': record({**RUN_FIELDS, 'results': {'type': 'object'},
                              'items': array(record({'run_id': STRING, 'candidate_id': INTEGER,
                                                      'proposal_revision': INTEGER, 'position': INTEGER,
                                                      'status': STRING, 'result': {'type': ['object', 'null']}}))}),
    'AutomationControl': record(CONTROL_FIELDS),
    'AutomationPolicyHistory': record({
        'versions': array(record({'policy_id': INTEGER, 'revision': INTEGER, 'config': POLICY, 'actor': STRING,
                                  'reason': STRING, 'created_at': STRING})),
        'decisions': array(record({'policy_id': INTEGER, 'revision': INTEGER, 'state_revision': INTEGER,
                                   'enabled': BOOLEAN, 'actor': STRING, 'reason': STRING, 'created_at': STRING,
                                   'reviewed_simulation_id': NULL_STRING})),
    }),
}


def response_schema(method: str, path: str) -> dict:
    if path == '/automation/policies':
        return page(ref('AutomationPolicySummary')) if method == 'GET' else ref('AutomationPolicy')
    if path in {'/automation/policies/{policy_id}', '/automation/policies/{policy_id}/activation'}:
        return ref('AutomationPolicy')
    if path == '/automation/policies/{policy_id}/history':
        return ref('AutomationPolicyHistory')
    if path == '/automation/policies/{policy_id}/schedule':
        return record({'schedule': {'type': ['object', 'null'], 'properties': {
            'policy_id': INTEGER, 'next_check_at': {'type': 'number'},
            'last_checked_at': {'type': ['number', 'null']}, 'last_simulation_id': NULL_STRING,
            'last_run_id': NULL_STRING, 'failures': INTEGER, 'error_code': NULL_STRING}}})
    if path == '/automation/control':
        return ref('AutomationControl')
    if path == '/automation/control/history':
        return page(record({**CONTROL_FIELDS, 'actor': STRING, 'reason': STRING, 'created_at': STRING}))
    if path == '/automation/simulations':
        return page(ref('AutomationSimulationSummary'))
    if path == '/automation/runs':
        return page(ref('AutomationRunSummary'))
    if path == '/automation/runs/{run_id}':
        return ref('AutomationRun')
    return ref('AutomationSimulation')
