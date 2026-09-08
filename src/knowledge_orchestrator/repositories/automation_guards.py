"""Elegibilidad de políticas en una sola transacción SQLite; no basta un dry-run anterior."""
from __future__ import annotations

import json
import sqlite3

from knowledge_orchestrator.domain.automation import AutomationDenied, AutomationPolicyConfig
from knowledge_orchestrator.services.provenance import source_provenance_in


def policy_blockers(connection: sqlite3.Connection, config: AutomationPolicyConfig,
                    candidate: sqlite3.Row) -> tuple[list[str], dict | None]:
    blockers = []
    if candidate['status'] != 'PENDING_REVIEW':
        blockers.append('PROPOSAL_NOT_REVIEWABLE')
    if candidate['relation'] not in config.relations:
        blockers.append('RELATION_NOT_ALLOWED')
    if candidate['confidence'] is None or candidate['confidence'] < config.min_confidence:
        blockers.append('CONFIDENCE_BELOW_POLICY')
    assessment = connection.execute('SELECT snapshot_json FROM maintenance_proposal_versions '
                                    'WHERE candidate_id=? AND revision=?',
                                    (candidate['candidate_id'], candidate['proposal_revision'])).fetchone()
    if assessment is None:
        blockers.append('ASSESSMENT_MISSING')
        snapshot = {}
    else:
        snapshot = json.loads(assessment['snapshot_json'])
    for field, limit, code in (('affected_claim_ids', config.max_claims_per_task, 'CLAIM_LIMIT'),
                                ('affected_note_ids', config.max_notes_per_task, 'NOTE_LIMIT')):
        values = snapshot.get(field)
        if not isinstance(values, list) or not values or len(values) > limit:
            blockers.append(code)
    claims = []
    for identifier in (candidate['target_claim_id'], candidate['new_claim_id']):
        claim = connection.execute('SELECT * FROM knowledge_claims WHERE claim_id=?', (identifier,)).fetchone()
        claims.append(claim)
        if claim is None or claim['status'] != 'ACTIVE' or claim['knowledge_state'] != 'CURRENT':
            blockers.append('CLAIM_NOT_CURRENT')
        elif claim['manual_lock']:
            blockers.append('MANUAL_LOCK')
        elif claim['claim_type'] not in config.claim_types:
            blockers.append('CLAIM_TYPE_NOT_ALLOWED')
    new_claim = claims[1]
    if new_claim is None:
        return sorted(set([*blockers, 'EVIDENCE_MISSING'])), None
    source = source_provenance_in(connection, new_claim['source_capture_id']).get('monitoring')
    if not source:
        return sorted(set([*blockers, 'MONITORED_PROVENANCE_REQUIRED'])), None
    identifier = source['monitored_source_id']
    if identifier not in config.source_ids:
        blockers.append('SOURCE_OUTSIDE_POLICY')
    current = connection.execute('SELECT config_json,revision FROM monitored_sources WHERE source_id=?',
                                 (identifier,)).fetchone()
    if current is None:
        return sorted(set([*blockers, 'SOURCE_MISSING'])), None
    current_config = json.loads(current['config_json'])
    observed = {'source_id': identifier, 'revision': current['revision'],
                'trust_level': current_config['trust_level'], 'source_role': current_config['source_role']}
    if current['revision'] != source['source_revision']:
        blockers.append('SOURCE_REVISION_CHANGED')
    if not current_config['enabled']:
        blockers.append('SOURCE_DISABLED')
    if current_config['kind'] not in config.source_kinds:
        blockers.append('SOURCE_KIND_NOT_ALLOWED')
    if current_config['source_role'] not in config.source_roles:
        blockers.append('SOURCE_ROLE_NOT_ALLOWED')
    if current_config['trust_level'] < config.min_source_trust:
        blockers.append('SOURCE_TRUST_BELOW_POLICY')
    return sorted(set(blockers)), observed


def check_run_authorization(connection: sqlite3.Connection,
                            authorization: sqlite3.Row | dict) -> AutomationPolicyConfig:
    policy = connection.execute('SELECT * FROM automation_policies WHERE policy_id=?',
                                (authorization['policy_id'],)).fetchone()
    if policy is None or not policy['enabled'] or not policy['approved_by']:
        raise AutomationDenied('POLICY_DISABLED')
    if (policy['revision'], policy['state_revision']) != (
            authorization['policy_revision'], authorization['policy_state_revision']):
        raise AutomationDenied('POLICY_CHANGED')
    control = connection.execute('SELECT * FROM automation_control WHERE singleton=1').fetchone()
    if control['paused']:
        raise AutomationDenied('AUTOMATION_PAUSED')
    if control['revision'] != authorization['control_revision']:
        raise AutomationDenied('CONTROL_CHANGED')
    return AutomationPolicyConfig(**json.loads(policy['config_json']))


def reserve_policy_application(connection: sqlite3.Connection, candidate: sqlite3.Row, *,
                               run_id: str, actor: str) -> None:
    run = connection.execute('SELECT * FROM automation_runs WHERE run_id=?', (run_id,)).fetchone()
    if run is None or run['status'] != 'RUNNING':
        raise AutomationDenied('RUN_NOT_ACTIVE')
    if actor != f"policy:{run['policy_id']}:revision:{run['policy_revision']}":
        raise AutomationDenied('POLICY_ACTOR_MISMATCH')
    item = connection.execute('SELECT * FROM automation_run_items WHERE run_id=? AND candidate_id=?',
                               (run_id, candidate['candidate_id'])).fetchone()
    if item is None or item['status'] != 'RUNNING' or item['proposal_revision'] != candidate['proposal_revision']:
        raise AutomationDenied('RUN_ITEM_CHANGED')
    config = check_run_authorization(connection, run)
    blockers, observed = policy_blockers(connection, config, candidate)
    if blockers:
        raise AutomationDenied('POLICY_INELIGIBLE', blockers)
    used_run = connection.execute('SELECT count(*) FROM automation_reservations WHERE run_id=?',
                                  (run_id,)).fetchone()[0]
    used_day = connection.execute('SELECT count(*) FROM automation_reservations WHERE policy_id=? '
                                  "AND utc_day=strftime('%Y-%m-%d','now')", (run['policy_id'],)).fetchone()[0]
    if used_run >= config.max_tasks_per_run:
        raise AutomationDenied('RUN_TASK_LIMIT')
    if used_day >= config.max_tasks_per_day:
        raise AutomationDenied('DAILY_TASK_LIMIT')
    if connection.execute('SELECT 1 FROM automation_reservations WHERE candidate_id=? AND proposal_revision=?',
                          (candidate['candidate_id'], candidate['proposal_revision'])).fetchone():
        raise AutomationDenied('PROPOSAL_ALREADY_RESERVED')
    connection.execute('INSERT INTO automation_reservations(run_id,candidate_id,proposal_revision,policy_id) '
                       'VALUES (?,?,?,?)', (run_id, candidate['candidate_id'], candidate['proposal_revision'],
                                           run['policy_id']))
    connection.execute('INSERT INTO events(event_type,message,details_json) VALUES (?,?,?)',
                       ('AUTOMATION_APPLICATION_RESERVED', 'Publicación autorizada por política y cupo reservado',
                        json.dumps({'run_id': run_id, 'policy_id': run['policy_id'],
                                    'policy_revision': run['policy_revision'],
                                    'control_revision': run['control_revision'],
                                    'candidate_id': candidate['candidate_id'],
                                    'proposal_revision': candidate['proposal_revision'], 'source': observed})))
