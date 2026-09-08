"""Planes automáticos fijados, recibos por tarea y recuperación de ejecuciones."""
from __future__ import annotations

import json
import uuid
from contextlib import closing

from knowledge_orchestrator.repositories.automation_guards import check_run_authorization
from knowledge_orchestrator.repositories.automation_repository import AutomationRepository
from knowledge_orchestrator.repositories.database import Database


class AutomationRunRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def queue(self, simulation_id: str, *, actor: str) -> dict:
        with self.database.transaction(immediate=True) as connection:
            run_id = self.queue_in(connection, simulation_id, actor=actor)
        return self.get(run_id)

    @staticmethod
    def queue_in(connection, simulation_id: str, *, actor: str) -> str:
        AutomationRepository._actor(actor, 'Encolar ejecución de política')
        existing = connection.execute('SELECT run_id FROM automation_runs WHERE simulation_id=?',
                                      (simulation_id,)).fetchone()
        if existing:
            return str(existing['run_id'])
        simulation = connection.execute('SELECT * FROM automation_simulations WHERE simulation_id=?',
                                        (simulation_id,)).fetchone()
        if simulation is None:
            raise LookupError('Simulación inexistente')
        check_run_authorization(connection, simulation)
        run_id = uuid.uuid4().hex
        connection.execute('INSERT INTO automation_runs(run_id,simulation_id,policy_id,policy_revision,'
                           'policy_state_revision,control_revision) VALUES (?,?,?,?,?,?)',
                           (run_id, simulation_id, simulation['policy_id'], simulation['policy_revision'],
                            simulation['policy_state_revision'], simulation['control_revision']))
        plan = json.loads(simulation['plan_json'])
        for position, item in enumerate(plan['items']):
            connection.execute('INSERT INTO automation_run_items VALUES (?,?,?,?,?,?)',
                               (run_id, item['candidate_id'], item['revision'], position,
                                'PENDING' if item['eligible'] else 'SKIPPED',
                                None if item['eligible'] else json.dumps({'reasons': item['blockers']})))
        AutomationRepository._event(connection, 'AUTOMATION_RUN_QUEUED',
                                     {'run_id': run_id, 'simulation_id': simulation_id, 'actor': actor})
        return run_id

    def get(self, run_id: str) -> dict:
        with closing(self.database.connect(readonly=True)) as connection:
            connection.execute('BEGIN')
            row = connection.execute('SELECT * FROM automation_runs WHERE run_id=?', (run_id,)).fetchone()
            if row is None:
                raise LookupError('Ejecución inexistente')
            result = dict(row)
            items = [dict(row) for row in connection.execute(
                'SELECT * FROM automation_run_items WHERE run_id=? ORDER BY position', (run_id,))]
        counts: dict[str, int] = {}
        for item in items:
            item['result'] = json.loads(item.pop('result_json') or 'null')
            counts[item['status']] = counts.get(item['status'], 0) + 1
        return {**result, 'items': items, 'results': counts}

    def claim_next(self) -> dict | None:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute("SELECT run_id FROM automation_runs WHERE status='READY' "
                                     'ORDER BY created_at,run_id LIMIT 1').fetchone()
            if row is None:
                return None
            connection.execute("UPDATE automation_runs SET status='RUNNING' WHERE run_id=?", (row['run_id'],))
        return self.get(row['run_id'])

    def start_item(self, run_id: str, candidate_id: int) -> None:
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute("UPDATE automation_run_items SET status='RUNNING' "
                                         "WHERE run_id=? AND candidate_id=? AND status='PENDING' AND EXISTS "
                                         "(SELECT 1 FROM automation_runs WHERE run_id=? AND status='RUNNING')",
                                         (run_id, candidate_id, run_id))
            if changed.rowcount != 1:
                raise ValueError('La tarea automática ya no está disponible')

    def finish_item(self, run_id: str, candidate_id: int, *, status: str, result: dict) -> None:
        if status not in {'APPLIED', 'SKIPPED', 'CONFLICT', 'FAILED', 'EXTERNALLY_RESOLVED'}:
            raise ValueError('Resultado de automatización inválido')
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute('UPDATE automation_run_items SET status=?,result_json=? '
                                         "WHERE run_id=? AND candidate_id=? AND status='RUNNING'",
                                         (status, json.dumps(result, ensure_ascii=False), run_id, candidate_id))
            if changed.rowcount:
                AutomationRepository._event(connection, 'AUTOMATION_ITEM_FINISHED',
                                             {'run_id': run_id, 'candidate_id': candidate_id, 'status': status})

    def finish_run(self, run_id: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute("UPDATE automation_runs SET status='COMPLETE',"
                                         "completed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE run_id=? "
                                         "AND status='RUNNING' AND NOT EXISTS (SELECT 1 FROM automation_run_items "
                                         "WHERE run_id=? AND status IN ('RUNNING','PENDING'))", (run_id, run_id))
            if changed.rowcount:
                AutomationRepository._event(connection, 'AUTOMATION_RUN_FINISHED', {'run_id': run_id})

    def pause_for_recovery(self, run_id: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute("UPDATE automation_runs SET status='RECOVERY_REQUIRED' "
                                         "WHERE run_id=? AND status='RUNNING'", (run_id,))
            if changed.rowcount:
                AutomationRepository._event(connection, 'AUTOMATION_RECOVERY_REQUIRED', {'run_id': run_id})

    def recover(self) -> None:
        """Solo al arrancar, después de recuperar las intenciones de publicación."""
        with self.database.transaction(immediate=True) as connection:
            connection.execute("UPDATE automation_run_items SET status='PENDING' WHERE status='RUNNING' "
                               'AND run_id IN (SELECT run_id FROM automation_runs '
                               "WHERE status IN ('RUNNING','RECOVERY_REQUIRED'))")
            connection.execute("UPDATE automation_runs SET status='READY' "
                               "WHERE status IN ('RUNNING','RECOVERY_REQUIRED')")
