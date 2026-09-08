"""Evaluación periódica acotada, con arrendamiento y confirmación transaccional."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from contextlib import closing

from knowledge_orchestrator.domain.automation import AutomationDenied
from knowledge_orchestrator.repositories.automation_guards import check_run_authorization
from knowledge_orchestrator.repositories.automation_repository import AutomationRepository
from knowledge_orchestrator.repositories.automation_run_repository import AutomationRunRepository
from knowledge_orchestrator.repositories.database import Database


class AutomationScheduleRepository:
    interval_seconds = 60
    lease_seconds = 1200
    page_size = 1000

    def __init__(self, database: Database) -> None:
        self.database = database

    def lease_due(self) -> dict | None:
        now = time.time()
        with self.database.transaction(immediate=True) as connection:
            control = connection.execute('SELECT * FROM automation_control WHERE singleton=1').fetchone()
            if control['paused']:
                return None
            connection.execute('INSERT OR IGNORE INTO automation_schedules(policy_id) '
                               'SELECT policy_id FROM automation_policies WHERE enabled=1 AND approved_by IS NOT NULL')
            row = connection.execute(
                'SELECT s.*,p.revision AS policy_revision,p.state_revision AS policy_state_revision,p.config_json '
                'FROM automation_schedules s JOIN automation_policies p USING(policy_id) '
                'WHERE p.enabled=1 AND p.approved_by IS NOT NULL AND s.next_check_at<=? '
                'AND (s.lease_until IS NULL OR s.lease_until<=?) AND NOT EXISTS '
                '(SELECT 1 FROM automation_runs r WHERE r.policy_id=p.policy_id '
                "AND r.status IN ('READY','RUNNING','RECOVERY_REQUIRED')) "
                'ORDER BY s.next_check_at,s.policy_id LIMIT 1', (now, now)).fetchone()
            if row is None:
                return None
            token = uuid.uuid4().hex
            connection.execute('UPDATE automation_schedules SET lease_token=?,lease_until=? WHERE policy_id=?',
                               (token, now + self.lease_seconds, row['policy_id']))
            return {**dict(row), 'lease_token': token, 'control_revision': control['revision']}

    def selection(self, job: dict, *, limit: int | None = None, wrap: bool = True) -> tuple[list[dict], int]:
        page_size = self.page_size if limit is None else limit
        if type(page_size) is not int or not 1 <= page_size <= 1000:
            raise ValueError('Selecciona entre 1 y 1000 propuestas por página')
        sources = json.loads(job['config_json'])['source_ids']
        placeholders = ','.join('?' for _ in sources)
        # Prefiltro por recibos durables. La simulación verifica después su autenticidad.
        query = ('SELECT DISTINCT c.candidate_id,c.proposal_revision AS expected_revision '
                 'FROM update_candidates c JOIN knowledge_claims k ON k.claim_id=c.new_claim_id '
                 'JOIN api_ingestions i ON i.capture_id=k.source_capture_id '
                 'JOIN source_changes s ON s.ingestion_id=i.ingestion_id '
                 f"WHERE c.status='PENDING_REVIEW' AND s.source_id IN ({placeholders}) "
                 'AND c.candidate_id>? ORDER BY c.candidate_id LIMIT ?')
        with closing(self.database.connect(readonly=True)) as connection:
            connection.execute('BEGIN')
            rows = connection.execute(query, (*sources, job['candidate_cursor'], page_size)).fetchall()
            if not rows and job['candidate_cursor'] and wrap:
                rows = connection.execute(query, (*sources, 0, page_size)).fetchall()
        return [dict(row) for row in rows], rows[-1]['candidate_id'] if rows else 0

    @staticmethod
    def _lease(connection, job: dict, now: float):
        row = connection.execute('SELECT * FROM automation_schedules WHERE policy_id=? AND lease_token=? '
                                 'AND lease_until>?', (job['policy_id'], job['lease_token'], now)).fetchone()
        if row is None:
            raise AutomationDenied('SCHEDULE_LEASE_EXPIRED')
        return row

    def finish(self, job: dict, preview: dict, cursor: int) -> str | None:
        with self.database.transaction(immediate=True) as connection:
            now = time.time()
            self._lease(connection, job, now)
            check_run_authorization(connection, job)
            policy, control, plan = preview['policy'], preview['control'], preview['plan']
            if (policy['policy_id'], policy['revision'], policy['state_revision'], control['revision']) != (
                    job['policy_id'], job['policy_revision'], job['policy_state_revision'], job['control_revision']):
                raise AutomationDenied('SCHEDULE_PLAN_CHANGED')
            day = connection.execute("SELECT strftime('%Y-%m-%d','now')").fetchone()[0]
            fingerprint = hashlib.sha256(json.dumps(
                [job['control_revision'], day, plan], sort_keys=True, ensure_ascii=False,
                allow_nan=False).encode()).hexdigest()
            previous = connection.execute('SELECT simulation_id,run_id FROM automation_schedule_plans '
                                          'WHERE policy_id=? AND fingerprint=?',
                                          (job['policy_id'], fingerprint)).fetchone()
            if previous:
                simulation_id, run_id = previous['simulation_id'], previous['run_id']
            else:
                simulation_id = AutomationRepository(self.database).save_simulation_in(
                    connection, policy, control, plan, actor='scheduler')
                run_id = None
                if plan['counts']['eligible']:
                    run_id = AutomationRunRepository.queue_in(connection, simulation_id, actor='scheduler')
                connection.execute('INSERT INTO automation_schedule_plans VALUES (?,?,?,?)',
                                   (job['policy_id'], fingerprint, simulation_id, run_id))
            connection.execute('UPDATE automation_schedules SET next_check_at=?,last_checked_at=?,lease_token=NULL,'
                               'lease_until=NULL,last_fingerprint=?,last_simulation_id=?,last_run_id=?,candidate_cursor=?,'
                               'failures=0,error_code=NULL WHERE policy_id=?',
                               (now + self.interval_seconds, now, fingerprint, simulation_id, run_id, cursor,
                                job['policy_id']))
        return run_id

    def failed(self, job: dict, code: str, *, oversized_candidate: dict | None = None) -> None:
        if code not in {'AUTHORIZATION_CHANGED', 'PLAN_TOO_LARGE', 'EVALUATION_FAILED'}:
            raise ValueError('Código de error de planificación inválido')
        with self.database.transaction(immediate=True) as connection:
            now = time.time()
            try:
                row = self._lease(connection, job, now)
            except AutomationDenied:
                return
            failures = min(row['failures'] + 1, 16)
            connection.execute('UPDATE automation_schedules SET next_check_at=?,last_checked_at=?,lease_token=NULL,'
                               'lease_until=NULL,failures=?,error_code=?,candidate_cursor=COALESCE(?,candidate_cursor) '
                               'WHERE policy_id=?',
                               (now + min(3600, self.interval_seconds * 2 ** (failures - 1)), now,
                                failures, code, oversized_candidate['candidate_id'] if oversized_candidate else None,
                                job['policy_id']))
            AutomationRepository._event(connection, 'AUTOMATION_SCHEDULE_FAILED',
                                         {'policy_id': job['policy_id'], 'code': code,
                                          'oversized_candidate': oversized_candidate})
