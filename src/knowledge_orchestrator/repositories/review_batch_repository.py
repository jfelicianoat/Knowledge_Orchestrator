"""Planes de revisión fijados y recibos recuperables por propuesta."""
from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import closing

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.repositories.database import Database


def encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class ReviewBatchRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def existing(self, owner: str, key: str, request: dict) -> dict | None:
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute('SELECT batch_id,request_json FROM review_batches WHERE owner=? AND create_key=?',
                                     (owner, key)).fetchone()
        if row is None:
            return None
        if row['request_json'] != encoded(request):
            raise KnowledgeConflict('La clave corresponde a otra selección')
        return self.get(row['batch_id'], owner=owner)

    def list(self, *, owner: str, limit: int = 100, offset: int = 0) -> list[dict]:
        if not 1 <= limit <= 1000 or not 0 <= offset <= 1000000:
            raise ValueError('Paginación de lotes inválida')
        with closing(self.database.connect(readonly=True)) as connection:
            return [dict(row) for row in connection.execute(
                'SELECT batch_id,status,created_at,confirmed_at,completed_at FROM review_batches WHERE owner=? '
                'ORDER BY created_at DESC,batch_id DESC LIMIT ? OFFSET ?', (owner, limit, offset))]

    def create(self, *, owner: str, key: str, request: dict, plan: dict) -> dict:
        batch_id = uuid.uuid4().hex
        payload = encoded(plan)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self.database.transaction(immediate=True) as connection:
            connection.execute('INSERT INTO review_batches(batch_id,owner,create_key,request_json,plan_json,plan_hash) '
                               'VALUES (?,?,?,?,?,?) ON CONFLICT(owner,create_key) DO NOTHING',
                               (batch_id, owner, key, encoded(request), payload, digest))
            saved = connection.execute(
                'SELECT batch_id,request_json FROM review_batches WHERE owner=? AND create_key=?',
                (owner, key)).fetchone()
            if saved['request_json'] != encoded(request):
                raise KnowledgeConflict('La clave corresponde a otra selección')
            if saved['batch_id'] == batch_id:
                for index, item in enumerate(plan['items']):
                    connection.execute('INSERT INTO review_batch_items VALUES (?,?,?,?,?,?)',
                                       (batch_id, index, item['candidate_id'], item['revision'],
                                        'PENDING' if item['eligible'] else 'SKIPPED',
                                        None if item['eligible'] else encoded({'reasons': item['blockers']})))
                self._event(connection, 'REVIEW_BATCH_PREVIEWED', batch_id, owner)
            batch_id = saved['batch_id']
        return self.get(batch_id, owner=owner)

    def get(self, batch_id: str, *, owner: str) -> dict:
        with closing(self.database.connect(readonly=True)) as connection:
            connection.execute('BEGIN')
            row = connection.execute('SELECT * FROM review_batches WHERE batch_id=? AND owner=?',
                                     (batch_id, owner)).fetchone()
            if row is None:
                raise LookupError('Lote no disponible')
            result = dict(row)
            result['plan'] = json.loads(result.pop('plan_json'))
            result.pop('request_json')
            result.pop('create_key')
            result['items'] = []
            counts: dict[str, int] = {}
            for item in connection.execute('SELECT * FROM review_batch_items WHERE batch_id=? ORDER BY position',
                                           (batch_id,)):
                value = dict(item)
                value['result'] = json.loads(value.pop('result_json') or 'null')
                result['items'].append(value)
                counts[value['status']] = counts.get(value['status'], 0) + 1
            result['results'] = counts
            return result

    def confirm(self, batch_id: str, *, owner: str, plan_hash: str) -> dict:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute('SELECT * FROM review_batches WHERE batch_id=? AND owner=?',
                                     (batch_id, owner)).fetchone()
            if row is None:
                raise LookupError('Lote no disponible')
            if row['plan_hash'] != plan_hash:
                raise KnowledgeConflict('La confirmación no corresponde a esta vista previa')
            if row['status'] == 'DRAFT':
                connection.execute("UPDATE review_batches SET status='READY',"
                                   "confirmed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE batch_id=?", (batch_id,))
                self._event(connection, 'REVIEW_BATCH_CONFIRMED', batch_id, owner)
        return self.get(batch_id, owner=owner)

    def claim_next(self) -> dict | None:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute("SELECT batch_id,owner FROM review_batches WHERE status='READY' "
                                     'ORDER BY created_at,batch_id LIMIT 1').fetchone()
            if row is None:
                return None
            connection.execute("UPDATE review_batches SET status='RUNNING' WHERE batch_id=?", (row['batch_id'],))
        return self.get(row['batch_id'], owner=row['owner'])

    def start_item(self, batch_id: str, candidate_id: int) -> None:
        with self.database.transaction(immediate=True) as connection:
            connection.execute("UPDATE review_batch_items SET status='RUNNING' WHERE batch_id=? AND candidate_id=? "
                               "AND status='PENDING'", (batch_id, candidate_id))

    def finish_item(self, batch_id: str, candidate_id: int, *, status: str, result: dict) -> None:
        if status not in {'APPLIED', 'CONFLICT', 'FAILED', 'EXTERNALLY_RESOLVED'}:
            raise ValueError('Resultado de lote inválido')
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute('UPDATE review_batch_items SET status=?,result_json=? '
                                         "WHERE batch_id=? AND candidate_id=? AND status='RUNNING'",
                                         (status, encoded(result), batch_id, candidate_id))
            if changed.rowcount:
                connection.execute('INSERT INTO events(event_type,message,details_json) VALUES (?,?,?)',
                                   ('REVIEW_BATCH_ITEM_FINISHED', 'Resultado de revisión masiva registrado',
                                    encoded({'batch_id': batch_id, 'candidate_id': candidate_id, 'status': status})))

    def finish_batch(self, batch_id: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute("UPDATE review_batches SET status='COMPLETE',"
                                         "completed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE batch_id=? "
                                         "AND status='RUNNING' AND NOT EXISTS (SELECT 1 FROM review_batch_items "
                                         "WHERE batch_id=? AND status IN ('PENDING','RUNNING'))", (batch_id, batch_id))
            if changed.rowcount:
                self._event(connection, 'REVIEW_BATCH_COMPLETED', batch_id, 'worker:review')

    def recover(self) -> None:
        """Solo al arrancar, después de recuperar las intenciones de publicación."""
        with self.database.transaction(immediate=True) as connection:
            connection.execute("UPDATE review_batch_items SET status='PENDING' WHERE status='RUNNING' "
                               "AND batch_id IN (SELECT batch_id FROM review_batches "
                               "WHERE status IN ('RUNNING','RECOVERY_REQUIRED'))")
            connection.execute("UPDATE review_batches SET status='READY' "
                               "WHERE status IN ('RUNNING','RECOVERY_REQUIRED')")

    def pause_for_recovery(self, batch_id: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute("UPDATE review_batches SET status='RECOVERY_REQUIRED' "
                                         "WHERE batch_id=? AND status='RUNNING'", (batch_id,))
            if changed.rowcount:
                self._event(connection, 'REVIEW_BATCH_RECOVERY_REQUIRED', batch_id, 'worker:review')

    @staticmethod
    def _event(connection, event: str, batch_id: str, actor: str) -> None:
        connection.execute('INSERT INTO events(event_type,message,details_json) VALUES (?,?,?)',
                           (event, 'Estado de revisión masiva actualizado',
                            encoded({'batch_id': batch_id, 'actor': actor})))
