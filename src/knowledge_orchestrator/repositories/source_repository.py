"""Scheduler durable, historial y entrega recuperable de observaciones externas."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from contextlib import closing

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.domain.monitoring import FetchResult, SourceConfig
from knowledge_orchestrator.repositories.database import Database


class SourceRepository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _event(connection, kind: str, details: dict) -> None:
        connection.execute('INSERT INTO events(event_type, message, details_json) VALUES (?, ?, ?)',
                           (kind, 'Actividad de fuentes vigiladas', json.dumps(details)))

    @staticmethod
    def _source(row) -> dict:
        result = dict(row)
        result['config'] = json.loads(result.pop('config_json'))
        for key in ('owner', 'create_key', 'create_payload'):
            result.pop(key, None)
        return result

    def create(self, config: SourceConfig, *, actor: str, key: str) -> dict:
        payload = config.json()
        hashed_key = hashlib.sha256(key.encode()).hexdigest()
        with self.database.transaction(immediate=True) as connection:
            prior = connection.execute('SELECT * FROM monitored_sources WHERE owner=? AND create_key=?',
                                       (actor, hashed_key)).fetchone()
            if prior:
                if prior['create_payload'] != payload:
                    raise KnowledgeConflict('Clave utilizada con otra fuente')
                return self._source(prior)
            cursor = connection.execute(
                'INSERT INTO monitored_sources(config_json,owner,create_key,create_payload) VALUES (?,?,?,?)',
                (payload, actor, hashed_key, payload))
            source_id = cursor.lastrowid
            connection.execute('INSERT INTO source_revisions(source_id,revision,config_json,actor) VALUES (?,1,?,?)',
                               (source_id, payload, actor))
            self._event(connection, 'SOURCE_CREATED', {'source_id': source_id, 'actor': actor})
        assert source_id is not None
        return self.get(source_id)

    def get(self, source_id: int) -> dict:
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute('SELECT * FROM monitored_sources WHERE source_id=?', (source_id,)).fetchone()
            if row is None:
                raise LookupError('Fuente inexistente')
            return self._source(row)

    def list_sources(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        with closing(self.database.connect(readonly=True)) as connection:
            return [self._source(row) for row in connection.execute(
                'SELECT * FROM monitored_sources ORDER BY source_id LIMIT ? OFFSET ?', (limit, offset))]

    def update(self, source_id: int, config: SourceConfig, *, expected_revision: int, actor: str) -> dict:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute('SELECT * FROM monitored_sources WHERE source_id=?', (source_id,)).fetchone()
            if row is None:
                raise LookupError('Fuente inexistente')
            if row['revision'] != expected_revision:
                raise KnowledgeConflict('La configuración cambió; vuelva a abrirla')
            old = json.loads(row['config_json'])
            # Otra localización/tipo es otra identidad de contenido, aun dentro de la misma fuente.
            reset = old['location'] != config.location or old['kind'] != config.kind
            connection.execute(
                'UPDATE monitored_sources SET config_json=?,revision=revision+1,next_check_at=0,'
                'etag=NULL,last_modified=NULL,check_id=NULL,lease_until=NULL,failures=0,last_error_code=NULL,'
                'last_known_hash=CASE WHEN ? THEN NULL ELSE last_known_hash END WHERE source_id=?',
                (config.json(), reset, source_id))
            if reset:
                connection.execute('DELETE FROM source_items WHERE source_id=?', (source_id,))
            if row['check_id']:
                connection.execute("UPDATE source_checks SET status='SUPERSEDED',finished_at=? WHERE check_id=?",
                                   (time.time(), row['check_id']))
            connection.execute('INSERT INTO source_revisions(source_id,revision,config_json,actor) VALUES (?,?,?,?)',
                               (source_id, expected_revision + 1, config.json(), actor))
            self._event(connection, 'SOURCE_CONFIGURED', {'source_id': source_id, 'actor': actor,
                                                         'revision': expected_revision + 1})
        return self.get(source_id)

    def request_check(self, source_id: int, *, actor: str, key: str) -> dict:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute('SELECT * FROM monitored_sources WHERE source_id=?', (source_id,)).fetchone()
            if row is None:
                raise LookupError('Fuente inexistente')
            if not json.loads(row['config_json'])['enabled']:
                raise KnowledgeConflict('Active la fuente antes de comprobarla')
            hashed_key = hashlib.sha256(key.encode()).hexdigest()
            payload = json.dumps(['check', source_id])
            prior = connection.execute('SELECT payload FROM source_commands WHERE owner=? AND command_key=?',
                                       (actor, hashed_key)).fetchone()
            if prior and prior['payload'] != payload:
                raise KnowledgeConflict('Clave utilizada con otra operación')
            if not prior:
                connection.execute('INSERT INTO source_commands VALUES (?,?,?)', (actor, hashed_key, payload))
                connection.execute('UPDATE monitored_sources SET next_check_at=0 WHERE source_id=?', (source_id,))
                self._event(connection, 'SOURCE_CHECK_REQUESTED', {'source_id': source_id, 'actor': actor})
        return self.get(source_id)

    def lease_due(self, *, now: float, limit: int = 4) -> list[dict]:
        jobs = []
        with self.database.transaction(immediate=True) as connection:
            expired = connection.execute(
                'SELECT source_id,check_id FROM monitored_sources WHERE lease_until<=?', (now,)).fetchall()
            for row in expired:
                connection.execute("UPDATE source_checks SET status='ABANDONED',finished_at=? WHERE check_id=?",
                                   (now, row['check_id']))
                connection.execute('UPDATE monitored_sources SET lease_until=NULL,check_id=NULL WHERE source_id=?',
                                   (row['source_id'],))
                self._event(connection, 'SOURCE_CHECK_RECOVERED', dict(row))
            rows = connection.execute(
                'SELECT * FROM monitored_sources WHERE next_check_at<=? AND check_id IS NULL '
                "AND json_extract(config_json,'$.enabled')=1 ORDER BY next_check_at,source_id LIMIT ?",
                (now, limit)).fetchall()
            for row in rows:
                check_id = uuid.uuid4().hex
                connection.execute('UPDATE monitored_sources SET check_id=?,lease_until=? WHERE source_id=?',
                                   (check_id, now + 90, row['source_id']))
                connection.execute('INSERT INTO source_checks(check_id,source_id,source_revision,status,started_at) '
                                   "VALUES (?,?,?,'RUNNING',?)", (check_id, row['source_id'], row['revision'], now))
                job = self._source(row)
                job['check_id'] = check_id
                jobs.append(job)
        return jobs

    def finish(self, job: dict, result: FetchResult | None, *, now: float, error: str | None = None) -> bool:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute('SELECT * FROM monitored_sources WHERE source_id=?',
                                     (job['source_id'],)).fetchone()
            if row['check_id'] != job['check_id'] or row['revision'] != job['revision'] or row['lease_until'] <= now:
                return False
            config = SourceConfig(**json.loads(row['config_json']))
            changes = 0
            fingerprint = row['last_known_hash']
            if result is not None and not error and not result.not_modified:
                hashes = []
                for item in result.items:
                    hashes.append([item.key, item.content_hash])
                    previous = connection.execute(
                        'SELECT content_hash FROM source_items WHERE source_id=? AND item_key=?',
                        (job['source_id'], item.key)).fetchone()
                    if previous and previous['content_hash'] == item.content_hash:
                        continue
                    change_id = uuid.uuid4().hex
                    provenance = {'monitored_source_id': job['source_id'], 'source_revision': job['revision'],
                                  'source_change_id': change_id, 'trust_level': config.trust_level,
                                  'source_role': config.source_role, 'scope': config.scope, 'source_kind': config.kind}
                    connection.execute(
                        'INSERT INTO source_changes(change_id,check_id,source_id,source_revision,'
                        'item_key,previous_hash,'
                        'content_hash,title,content,source_url,provenance_json,observed_at,status) '
                        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (change_id, job['check_id'], job['source_id'], job['revision'], item.key,
                         previous['content_hash'] if previous else None, item.content_hash, item.title, item.content,
                         item.url, json.dumps(provenance), now,
                         'READY' if config.ingestion_policy == 'ingest' else 'REVIEW'))
                    connection.execute('INSERT INTO source_items VALUES (?,?,?,?) ON CONFLICT(source_id,item_key) '
                                       'DO UPDATE SET content_hash=excluded.content_hash,'
                                       'last_change_id=excluded.last_change_id',
                                       (job['source_id'], item.key, item.content_hash, change_id))
                    changes += 1
                fingerprint = hashlib.sha256(json.dumps(sorted(hashes)).encode()).hexdigest()
            failures = row['failures'] + 1 if error else 0
            delay = min(3600, 30 * 2 ** min(failures, 7)) if error else config.interval_seconds
            status = 'ERROR' if error else 'CHANGED' if changes else 'UNCHANGED'
            connection.execute('UPDATE source_checks SET status=?,finished_at=?,error_code=? WHERE check_id=?',
                               (status, now, error, job['check_id']))
            connection.execute(
                'UPDATE monitored_sources SET next_check_at=?,last_checked_at=?,failures=?,last_error_code=?,'
                'check_id=NULL,lease_until=NULL,last_known_hash=?,last_changed_at=CASE WHEN ? THEN ? '
                'ELSE last_changed_at END,etag=?,last_modified=? WHERE source_id=?',
                (now + delay, now, failures, error, fingerprint, changes, now,
                 (result.etag if result.etag is not None else row['etag']) if result and result.not_modified else
                 result.etag if result else row['etag'],
                 (result.last_modified if result.last_modified is not None else row['last_modified'])
                 if result and result.not_modified else result.last_modified if result else row['last_modified'],
                 job['source_id']))
            self._event(connection, 'SOURCE_CHECK_' + status,
                        {'source_id': job['source_id'], 'check_id': job['check_id'],
                         'changes': changes, 'error': error})
        return True

    def history(self, source_id: int, *, limit: int = 100, offset: int = 0) -> list[dict]:
        self.get(source_id)
        with closing(self.database.connect(readonly=True)) as connection:
            return [dict(row) for row in connection.execute('SELECT * FROM source_checks WHERE source_id=? '
                                                            'ORDER BY started_at DESC LIMIT ? OFFSET ?',
                                                            (source_id, limit, offset))]

    def changes(self, *, source_id: int | None = None, status: str | None = None,
                limit: int = 100, offset: int = 0, delivery_due: float | None = None) -> list[dict]:
        with closing(self.database.connect(readonly=True)) as connection:
            return [dict(row) for row in connection.execute(
                'SELECT change_id,source_id,source_revision,title,status,observed_at,previous_hash,content_hash,'
                'ingestion_id,delivery_error FROM source_changes WHERE (? IS NULL OR source_id=?) '
                'AND (? IS NULL OR status=?) AND (? IS NULL OR next_delivery_at<=?) '
                'ORDER BY observed_at DESC,change_id LIMIT ? OFFSET ?',
                (source_id, source_id, status, status, delivery_due, delivery_due, limit, offset))]

    def change(self, change_id: str) -> dict:
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute('SELECT * FROM source_changes WHERE change_id=?', (change_id,)).fetchone()
            if row is None:
                raise LookupError('Cambio inexistente')
            result = dict(row)
            result['provenance'] = json.loads(result.pop('provenance_json'))
            return result

    def queue_ingestion(self, change_id: str, *, actor: str) -> dict:
        with self.database.transaction(immediate=True) as connection:
            updated = connection.execute(
                "UPDATE source_changes SET status='READY' WHERE change_id=? AND status='REVIEW'", (change_id,))
            if updated.rowcount:
                self._event(connection, 'SOURCE_CHANGE_ACCEPTED', {'change_id': change_id, 'actor': actor})
        return self.change(change_id)

    def delivery_failed(self, change_id: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute('SELECT delivery_failures,status FROM source_changes WHERE change_id=?',
                                     (change_id,)).fetchone()
            if row['status'] != 'READY':
                return
            failures = row['delivery_failures'] + 1
            connection.execute("UPDATE source_changes SET delivery_failures=?,delivery_error='INGESTION_ERROR',"
                               'next_delivery_at=? WHERE change_id=?',
                               (failures, time.time() + min(3600, 30 * 2 ** min(failures, 7)), change_id))
            self._event(connection, 'SOURCE_DELIVERY_ERROR', {'change_id': change_id, 'attempt': failures})

    def delivered(self, change_id: str, ingestion_id: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            updated = connection.execute("UPDATE source_changes SET status='DELIVERED',ingestion_id=?,"
                                         'delivery_error=NULL '
                                         "WHERE change_id=? AND status='READY'", (ingestion_id, change_id))
            if updated.rowcount:
                self._event(connection, 'SOURCE_CHANGE_DELIVERED',
                            {'change_id': change_id, 'ingestion_id': ingestion_id})
