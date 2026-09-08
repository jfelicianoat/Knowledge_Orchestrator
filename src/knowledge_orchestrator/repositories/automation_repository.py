"""Versiones, decisiones explícitas e interruptor de nuevas aplicaciones automáticas."""
from __future__ import annotations

import json
import re
import uuid
from contextlib import closing

from knowledge_orchestrator.domain.automation import AutomationPolicyConfig
from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.repositories.database import Database


class AutomationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _actor(actor: str, reason: str) -> None:
        if not isinstance(actor, str) or not 1 <= len(actor.strip()) <= 200 \
                or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000:
            raise ValueError('La decisión requiere actor y motivo explícitos')

    @staticmethod
    def _policy(connection, policy_id: int):
        row = connection.execute('SELECT * FROM automation_policies WHERE policy_id=?', (policy_id,)).fetchone()
        if row is None:
            raise LookupError('Política inexistente')
        return row

    @staticmethod
    def _sources(connection, config: AutomationPolicyConfig) -> None:
        for source_id in config.source_ids:
            if not connection.execute('SELECT 1 FROM monitored_sources WHERE source_id=?', (source_id,)).fetchone():
                raise ValueError('La política hace referencia a una fuente inexistente')

    @staticmethod
    def _event(connection, kind: str, details: dict) -> None:
        connection.execute('INSERT INTO events(event_type,message,details_json) VALUES (?,?,?)',
                           (kind, 'Decisión de gobernanza registrada', json.dumps(details, ensure_ascii=False)))

    def create(self, config: AutomationPolicyConfig, *, actor: str, key: str) -> dict:
        self._actor(actor, 'Crear política')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,200}', key):
            raise ValueError('La creación requiere clave idempotente')
        payload = config.json()
        with self.database.transaction(immediate=True) as connection:
            previous = connection.execute('SELECT policy_id,create_payload FROM automation_policies '
                                          'WHERE created_by=? AND create_key=?', (actor, key)).fetchone()
            if previous:
                if previous['create_payload'] != payload:
                    raise KnowledgeConflict('La clave corresponde a otra configuración')
                policy_id = previous['policy_id']
            else:
                self._sources(connection, config)
                policy_id = connection.execute('INSERT INTO automation_policies('
                                               'config_json,created_by,create_key,create_payload) VALUES (?,?,?,?)',
                                               (payload, actor, key, payload)).lastrowid
                connection.execute('INSERT INTO automation_policy_versions('
                                   'policy_id,revision,config_json,actor,reason) '
                                   "VALUES (?,1,?,?,'Creación de política desactivada')", (policy_id, payload, actor))
                connection.execute('INSERT INTO automation_policy_decisions('
                                   'policy_id,revision,state_revision,enabled,actor,reason) '
                                   "VALUES (?,1,1,0,?,'Creación de política desactivada')", (policy_id, actor))
                self._event(connection, 'AUTOMATION_POLICY_CREATED', {'policy_id': policy_id, 'actor': actor})
        assert policy_id is not None
        return self.get(policy_id)

    def get(self, policy_id: int) -> dict:
        with closing(self.database.connect(readonly=True)) as connection:
            result = dict(self._policy(connection, policy_id))
        result['config'] = json.loads(result.pop('config_json'))
        result['enabled'] = bool(result['enabled'])
        result.pop('create_key')
        result.pop('create_payload')
        return result

    def list(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        if not 1 <= limit <= 1000 or not 0 <= offset <= 1000000:
            raise ValueError('Paginación de políticas inválida')
        with closing(self.database.connect(readonly=True)) as connection:
            rows = connection.execute('SELECT policy_id,revision,state_revision,enabled,approved_by,'
                                      "json_extract(config_json,'$.name') AS name FROM automation_policies "
                                      'ORDER BY policy_id DESC LIMIT ? OFFSET ?', (limit, offset)).fetchall()
        return [dict(row) for row in rows]

    def update(self, policy_id: int, config: AutomationPolicyConfig, *, expected_revision: int,
               expected_state_revision: int, actor: str, reason: str) -> dict:
        self._actor(actor, reason)
        with self.database.transaction(immediate=True) as connection:
            row = self._policy(connection, policy_id)
            self._expected(row, expected_revision, expected_state_revision)
            self._sources(connection, config)
            revision, state = row['revision'] + 1, row['state_revision'] + 1
            connection.execute('INSERT INTO automation_policy_versions(policy_id,revision,config_json,actor,reason) '
                               'VALUES (?,?,?,?,?)', (policy_id, revision, config.json(), actor, reason))
            connection.execute('UPDATE automation_policies SET config_json=?,revision=?,state_revision=?,enabled=0,'
                               'approved_by=NULL,approved_at=NULL WHERE policy_id=?',
                               (config.json(), revision, state, policy_id))
            connection.execute('INSERT INTO automation_policy_decisions('
                               'policy_id,revision,state_revision,enabled,actor,reason) VALUES (?,?,?,0,?,?)',
                               (policy_id, revision, state, actor, reason))
            self._event(connection, 'AUTOMATION_POLICY_REVISED', {'policy_id': policy_id, 'revision': revision,
                                                                 'state_revision': state, 'actor': actor})
        return self.get(policy_id)

    @staticmethod
    def _expected(row, revision: int, state_revision: int) -> None:
        if type(revision) is not int or type(state_revision) is not int \
                or (row['revision'], row['state_revision']) != (revision, state_revision):
            raise KnowledgeConflict('La política o su activación cambiaron desde que se abrió')

    def set_enabled(self, policy_id: int, enabled: bool, *, expected_revision: int,
                    expected_state_revision: int, actor: str, reason: str,
                    reviewed_simulation_id: str | None = None) -> dict:
        self._actor(actor, reason)
        if type(enabled) is not bool:
            raise ValueError('Activación inválida')
        with self.database.transaction(immediate=True) as connection:
            row = self._policy(connection, policy_id)
            self._expected(row, expected_revision, expected_state_revision)
            if reviewed_simulation_id is not None:
                simulation = connection.execute('SELECT * FROM automation_simulations WHERE simulation_id=?',
                                                (reviewed_simulation_id,)).fetchone()
                control = connection.execute('SELECT revision FROM automation_control WHERE singleton=1').fetchone()
                if simulation is None or (simulation['policy_id'], simulation['policy_revision'],
                                          simulation['policy_state_revision'], simulation['control_revision']) != (
                        policy_id, expected_revision, expected_state_revision, control['revision']):
                    raise KnowledgeConflict('La simulación revisada no corresponde a la configuración actual')
            state = row['state_revision'] + 1
            connection.execute('UPDATE automation_policies SET enabled=?,state_revision=?,approved_by=?,approved_at='
                               "CASE WHEN ? THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NULL END WHERE policy_id=?",
                               (enabled, state, actor if enabled else None, enabled, policy_id))
            connection.execute('INSERT INTO automation_policy_decisions('
                               'policy_id,revision,state_revision,enabled,actor,reason,reviewed_simulation_id) '
                               'VALUES (?,?,?,?,?,?,?)',
                               (policy_id, row['revision'], state, enabled, actor, reason, reviewed_simulation_id))
            self._event(connection, 'AUTOMATION_POLICY_ENABLED' if enabled else 'AUTOMATION_POLICY_DISABLED',
                        {'policy_id': policy_id, 'revision': row['revision'], 'state_revision': state, 'actor': actor})
        return self.get(policy_id)

    def control(self) -> dict:
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute('SELECT revision,paused FROM automation_control WHERE singleton=1').fetchone()
        return {'revision': row['revision'], 'paused': bool(row['paused'])}

    def set_paused(self, paused: bool, *, expected_revision: int, actor: str, reason: str) -> dict:
        self._actor(actor, reason)
        if type(paused) is not bool or type(expected_revision) is not int:
            raise ValueError('Control de automatización inválido')
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute('SELECT revision FROM automation_control WHERE singleton=1').fetchone()
            if row['revision'] != expected_revision:
                raise KnowledgeConflict('El control global cambió desde que se abrió')
            revision = expected_revision + 1
            connection.execute('UPDATE automation_control SET paused=?,revision=? WHERE singleton=1',
                               (paused, revision))
            connection.execute('INSERT INTO automation_control_history(revision,paused,actor,reason) VALUES (?,?,?,?)',
                               (revision, paused, actor, reason))
            self._event(connection, 'AUTOMATION_PAUSED' if paused else 'AUTOMATION_RESUMED',
                        {'revision': revision, 'actor': actor})
        return self.control()

    def history(self, policy_id: int) -> dict:
        with closing(self.database.connect(readonly=True)) as connection:
            connection.execute('BEGIN')
            self._policy(connection, policy_id)
            versions = [dict(row) for row in connection.execute(
                'SELECT * FROM automation_policy_versions WHERE policy_id=? ORDER BY revision', (policy_id,))]
            decisions = [dict(row) for row in connection.execute(
                'SELECT * FROM automation_policy_decisions WHERE policy_id=? ORDER BY state_revision', (policy_id,))]
        for version in versions:
            version['config'] = json.loads(version.pop('config_json'))
        return {'versions': versions, 'decisions': decisions}

    def save_simulation(self, policy: dict, control: dict, plan: dict, *, actor: str) -> dict:
        with self.database.transaction(immediate=True) as connection:
            identifier = self.save_simulation_in(connection, policy, control, plan, actor=actor)
        return self.simulation(identifier)

    def save_simulation_in(self, connection, policy: dict, control: dict, plan: dict, *, actor: str) -> str:
        """Permite fijar simulación y ejecución en la misma transacción del scheduler."""
        self._actor(actor, 'Simulación')
        identifier = uuid.uuid4().hex
        payload = json.dumps(plan, ensure_ascii=False, allow_nan=False)
        if len(payload.encode()) > 8 * 1024 * 1024:
            raise ValueError('La simulación supera 8 MiB; selecciona menos propuestas')
        row = self._policy(connection, policy['policy_id'])
        self._expected(row, policy['revision'], policy['state_revision'])
        current = connection.execute('SELECT revision FROM automation_control WHERE singleton=1').fetchone()
        if current['revision'] != control['revision']:
            raise KnowledgeConflict('El control global cambió durante la simulación')
        connection.execute('INSERT INTO automation_simulations(simulation_id,policy_id,policy_revision,'
                           'policy_state_revision,control_revision,plan_json,actor) VALUES (?,?,?,?,?,?,?)',
                           (identifier, policy['policy_id'], policy['revision'], policy['state_revision'],
                            control['revision'], payload, actor))
        self._event(connection, 'AUTOMATION_SIMULATED', {'simulation_id': identifier, 'actor': actor})
        return identifier

    def simulation(self, simulation_id: str) -> dict:
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute('SELECT * FROM automation_simulations WHERE simulation_id=?',
                                     (simulation_id,)).fetchone()
        if row is None:
            raise LookupError('Simulación inexistente')
        result = dict(row)
        result['plan'] = json.loads(result.pop('plan_json'))
        return result
