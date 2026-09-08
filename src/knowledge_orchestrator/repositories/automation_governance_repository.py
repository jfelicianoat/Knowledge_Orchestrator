"""Solicitudes de simulación idempotentes y lecturas paginadas de gobernanza."""
from __future__ import annotations

import json
from contextlib import closing

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.repositories.automation_repository import AutomationRepository


class AutomationGovernanceRepository:
    def __init__(self, policies: AutomationRepository) -> None:
        self.policies, self.database = policies, policies.database

    @staticmethod
    def _request(connection, actor: str, key: str, payload: str) -> str | None:
        row = connection.execute('SELECT request_json,simulation_id FROM automation_simulation_requests '
                                 'WHERE actor=? AND request_key=?', (actor, key)).fetchone()
        if row is None:
            return None
        if row['request_json'] != payload:
            raise KnowledgeConflict('La clave de simulación corresponde a otra solicitud')
        return str(row['simulation_id'])

    def previous(self, actor: str, key: str, payload: str) -> str | None:
        with closing(self.database.connect(readonly=True)) as connection:
            return self._request(connection, actor, key, payload)

    def save(self, actor: str, key: str, payload: str, preview: dict) -> dict:
        with self.database.transaction(immediate=True) as connection:
            identifier = self._request(connection, actor, key, payload)
            if identifier is None:
                identifier = self.policies.save_simulation_in(
                    connection, preview['policy'], preview['control'], preview['plan'], actor=actor)
                connection.execute('INSERT INTO automation_simulation_requests VALUES (?,?,?,?)',
                                   (actor, key, payload, identifier))
        return self.policies.simulation(identifier)

    @staticmethod
    def _pagination(limit: int, offset: int) -> None:
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 1000 or not 0 <= offset <= 1000000:
            raise ValueError('Paginación inválida')

    def history(self, policy_id: int, *, limit: int = 100, offset: int = 0) -> dict:
        self._pagination(limit, offset)
        with closing(self.database.connect(readonly=True)) as connection:
            connection.execute('BEGIN')
            self.policies._policy(connection, policy_id)
            versions = [dict(row) for row in connection.execute(
                'SELECT * FROM automation_policy_versions WHERE policy_id=? ORDER BY revision DESC LIMIT ? OFFSET ?',
                (policy_id, limit, offset))]
            decisions = [dict(row) for row in connection.execute(
                'SELECT * FROM automation_policy_decisions WHERE policy_id=? '
                'ORDER BY state_revision DESC LIMIT ? OFFSET ?', (policy_id, limit, offset))]
        for version in versions:
            version['config'] = json.loads(version.pop('config_json'))
        for decision in decisions:
            decision['enabled'] = bool(decision['enabled'])
        return {'versions': versions, 'decisions': decisions}

    def control_history(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        self._pagination(limit, offset)
        with closing(self.database.connect(readonly=True)) as connection:
            rows = [dict(row) for row in connection.execute(
                'SELECT * FROM automation_control_history ORDER BY revision DESC LIMIT ? OFFSET ?', (limit, offset))]
        for row in rows:
            row['paused'] = bool(row['paused'])
        return rows

    def schedule(self, policy_id: int) -> dict | None:
        with closing(self.database.connect(readonly=True)) as connection:
            connection.execute('BEGIN')
            self.policies._policy(connection, policy_id)
            row = connection.execute('SELECT policy_id,next_check_at,last_checked_at,last_simulation_id,last_run_id,'
                                     'failures,error_code FROM automation_schedules WHERE policy_id=?',
                                     (policy_id,)).fetchone()
        return dict(row) if row else None

    def list_records(self, kind: str, *, policy_id: int | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        self._pagination(limit, offset)
        columns = {
            'runs': 'run_id,simulation_id,policy_id,policy_revision,policy_state_revision,control_revision,'
                    'status,created_at,completed_at',
            'simulations': 'simulation_id,policy_id,policy_revision,policy_state_revision,control_revision,'
                           'actor,created_at',
        }
        if kind not in columns:
            raise ValueError('Tipo de registro inválido')
        with closing(self.database.connect(readonly=True)) as connection:
            query = f'SELECT {columns[kind]} FROM automation_{kind}'
            where, params = (' WHERE policy_id=?', (policy_id,)) if policy_id is not None else ('', ())
            rows = connection.execute(query + where + f' ORDER BY created_at DESC,{kind[:-1]}_id DESC LIMIT ? OFFSET ?',
                                      (*params, limit, offset)).fetchall()
        return [dict(row) for row in rows]
