"""Trabajos de consulta: propiedad, idempotencia y recuperación de envíos al Broker."""
from __future__ import annotations

import json
from contextlib import closing

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.repositories.database import Database


class QueryRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, query_id: str, *, owner: str | None = None) -> dict:
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute(
                'SELECT * FROM knowledge_queries WHERE query_id = ? AND (? IS NULL OR owner = ?)',
                (query_id, owner, owner),
            ).fetchone()
            if row is None:
                raise LookupError('Consulta inexistente')
            return dict(row)

    def existing(self, owner: str, key_hash: str, payload_hash: str) -> dict | None:
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute(
                'SELECT * FROM knowledge_queries WHERE owner = ? AND key_hash = ?', (owner, key_hash),
            ).fetchone()
            if row and row['payload_hash'] != payload_hash:
                raise KnowledgeConflict('Idempotency-Key ya utilizada con otra consulta')
            return dict(row) if row else None

    def create(self, *, query_id: str, owner: str, key_hash: str, payload_hash: str,
               state: str, request: dict, snapshot: dict, result: dict | None) -> dict:
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                'INSERT INTO knowledge_queries(query_id, owner, key_hash, payload_hash, knowledge_state, status, '
                'request_json, snapshot_json, result_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) '
                'ON CONFLICT(owner, key_hash) DO NOTHING',
                (query_id, owner, key_hash, payload_hash, state, 'SUCCESS' if result is not None else 'READY',
                 json.dumps(request, ensure_ascii=False), json.dumps(snapshot, ensure_ascii=False),
                 json.dumps(result, ensure_ascii=False) if result is not None else None),
            )
            row = connection.execute(
                'SELECT * FROM knowledge_queries WHERE owner = ? AND key_hash = ?', (owner, key_hash),
            ).fetchone()
            if row['payload_hash'] != payload_hash:
                raise KnowledgeConflict('Idempotency-Key ya utilizada con otra consulta')
            if row['query_id'] == query_id:
                self._event(connection, query_id, 'QUERY_CREATED', {'owner': owner, 'state': state})
            return dict(row)

    def ready(self) -> list[dict]:
        with closing(self.database.connect(readonly=True)) as connection:
            return [dict(r) for r in connection.execute(
                "SELECT * FROM knowledge_queries WHERE status = 'READY' AND (next_retry_at IS NULL OR "
                "next_retry_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) ORDER BY created_at LIMIT 10"
            )]

    def active(self) -> list[dict]:
        with closing(self.database.connect(readonly=True)) as connection:
            return [dict(r) for r in connection.execute(
                "SELECT * FROM knowledge_queries WHERE status IN ('QUEUED', 'PROCESSING') ORDER BY updated_at LIMIT 50"
            )]

    def claim(self, query_id: str) -> dict | None:
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE knowledge_queries SET status = 'SUBMITTING', attempt = attempt + 1 "
                "WHERE query_id = ? AND status = 'READY'", (query_id,),
            )
            if cursor.rowcount != 1:
                return None
            return dict(connection.execute(
                'SELECT * FROM knowledge_queries WHERE query_id = ?', (query_id,),
            ).fetchone())

    def transition(self, query_id: str, *, status: str, broker_task_id: str | None = None,
                   status_url: str | None = None, retry_at: str | None = None,
                   error_code: str | None = None, result: dict | None = None) -> None:
        if status not in {'READY', 'QUEUED', 'PROCESSING', 'SUCCESS', 'ERROR', 'STALE'}:
            raise ValueError('Estado de consulta inválido')
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute('SELECT status FROM knowledge_queries WHERE query_id = ?', (query_id,)).fetchone()
            if row is None or row['status'] in {'ERROR', 'STALE'} or (row['status'] == 'SUCCESS' and status != 'STALE'):
                return
            connection.execute(
                'UPDATE knowledge_queries SET status = ?, broker_task_id = COALESCE(?, broker_task_id), '
                'status_url = COALESCE(?, status_url), next_retry_at = ?, error_code = ?, '
                "result_json = COALESCE(?, result_json), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                'WHERE query_id = ?',
                (status, broker_task_id, status_url, retry_at, error_code,
                 json.dumps(result, ensure_ascii=False) if result is not None else None, query_id),
            )
            if row['status'] != status:
                self._event(connection, query_id, 'QUERY_STATE_CHANGED',
                            {'state': status, 'error_code': error_code, 'broker_task_id': broker_task_id})

    def recover(self) -> None:
        with self.database.transaction(immediate=True) as connection:
            connection.execute("UPDATE knowledge_queries SET status = 'READY' WHERE status = 'SUBMITTING'")

    @staticmethod
    def _event(connection, query_id: str, event: str, details: dict) -> None:
        connection.execute(
            'INSERT INTO events(event_type, message, details_json) VALUES (?, ?, ?)',
            (event, 'Consulta fundamentada de conocimiento', json.dumps({'query_id': query_id, **details})),
        )
