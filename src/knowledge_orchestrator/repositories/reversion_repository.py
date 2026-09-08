"""Planes, confirmaciones y recibos de compensación; ninguna actualización original se borra."""
from __future__ import annotations

import json
import re
import uuid
from contextlib import closing

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.repositories.database import Database
from knowledge_orchestrator.repositories.reversion_guards import encoded, snapshot, text_hash


class ReversionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def request(candidate_id: int, revision: int, actor: str, key: str) -> str:
        if type(candidate_id) is not int or candidate_id < 1 or type(revision) is not int or revision < 1 \
                or not isinstance(actor, str) or not 1 <= len(actor.strip()) <= 200 \
                or not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,200}', key):
            raise ValueError('La reversión requiere propuesta, revisión, actor y clave idempotente válidos')
        return encoded({'candidate_id': candidate_id, 'expected_revision': revision})

    def previous(self, actor: str, key: str, request: str) -> dict | None:
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute('SELECT * FROM maintenance_reversions WHERE owner=? AND request_key=?',
                                      (actor, key)).fetchone()
            if row is None:
                return None
            if row['request_json'] != request:
                raise KnowledgeConflict('La clave idempotente ya identifica otra solicitud')
            return self._record(row)

    def inspect(self, candidate_id: int, revision: int) -> dict:
        with closing(self.database.connect(readonly=True)) as connection:
            connection.execute('BEGIN')
            return snapshot(connection, candidate_id, revision)

    def create(self, plan: dict, *, actor: str, key: str, request: str) -> dict:
        value = encoded(plan)
        if len(value.encode('utf-8')) > 8 * 1024 * 1024:
            raise ValueError('La reversión supera 8 MiB; requiere una propuesta de revisión específica')
        with self.database.transaction(immediate=True) as connection:
            previous = connection.execute('SELECT * FROM maintenance_reversions WHERE owner=? AND request_key=?',
                                           (actor, key)).fetchone()
            if previous:
                if previous['request_json'] != request:
                    raise KnowledgeConflict('La clave idempotente ya identifica otra solicitud')
                return self._record(previous)
            if encoded(snapshot(connection, plan['candidate_id'], plan['proposal_revision'])) != value:
                raise KnowledgeConflict('El estado cambió mientras se preparaba la reversión')
            identifier = str(uuid.uuid4())
            connection.execute('INSERT INTO maintenance_reversions(reversion_id,candidate_id,owner,request_key,'
                               'request_json,plan_json,plan_hash) VALUES (?,?,?,?,?,?,?)',
                               (identifier, plan['candidate_id'], actor, key, request, value, text_hash(value)))
            connection.executemany('INSERT INTO maintenance_reversion_notes(reversion_id,note_id) VALUES (?,?)',
                                   [(identifier, note['note_id']) for note in plan['notes']])
        return self.get(identifier, actor=actor)

    @staticmethod
    def _record(row) -> dict:
        result = dict(row)
        result['plan'] = json.loads(result.pop('plan_json'))
        result.pop('request_json')
        result.pop('request_key')
        return result

    def get(self, identifier: str, *, actor: str) -> dict:
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute('SELECT * FROM maintenance_reversions WHERE reversion_id=? AND owner=?',
                                      (identifier, actor)).fetchone()
            if row is None:
                raise ValueError('Reversión inexistente o no accesible')
            return self._record(row)

    def begin(self, identifier: str, *, actor: str, plan_hash: str, reason: str) -> dict:
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 2000:
            raise ValueError('Confirmar la reversión requiere un motivo de hasta 2000 caracteres')
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute('SELECT * FROM maintenance_reversions WHERE reversion_id=? AND owner=?',
                                      (identifier, actor)).fetchone()
            if row is None:
                raise ValueError('Reversión inexistente o no accesible')
            if row['plan_hash'] != plan_hash:
                raise KnowledgeConflict('La confirmación no corresponde al plan revisado')
            if row['status'] == 'APPLIED':
                if row['reason'] != reason.strip():
                    raise KnowledgeConflict('La reversión ya se confirmó con otro motivo')
                return self._record(row)
            if row['status'] != 'PREVIEW':
                raise KnowledgeConflict('La reversión está iniciada o en conflicto; consulta su recibo')
            plan = json.loads(row['plan_json'])
            if encoded(snapshot(connection, row['candidate_id'], plan['proposal_revision'])) != row['plan_json']:
                raise KnowledgeConflict('El estado cambió desde la vista previa')
            revision = connection.execute('SELECT COALESCE(MAX(revision),0)+1 FROM note_revisions WHERE note_id=?',
                                           (plan['note_id'],)).fetchone()[0]
            connection.execute('INSERT INTO note_revisions(note_id,revision,content_text,content_hash,reason) '
                               'VALUES (?,?,?,?,?)',
                               (plan['note_id'], revision, plan['before'], plan['base_hash'],
                                f'REVERSION:{identifier}'))
            connection.execute("UPDATE maintenance_reversions SET status='APPLYING',reason=?,"
                               "confirmed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE reversion_id=?",
                               (reason.strip(), identifier))
            connection.execute('INSERT INTO events(event_type,message,details_json) VALUES (?,?,?)',
                               ('MAINTENANCE_REVERSION_CONFIRMED', 'Reversión confirmada explícitamente',
                                encoded({'reversion_id': identifier, 'candidate_id': row['candidate_id'],
                                         'actor': actor, 'plan_hash': plan_hash})))
        return self.get(identifier, actor=actor)

    def finish(self, identifier: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute('SELECT * FROM maintenance_reversions WHERE reversion_id=?',
                                      (identifier,)).fetchone()
            if row is None or row['status'] != 'APPLYING':
                return
            plan = json.loads(row['plan_json'])
            if encoded(snapshot(connection, row['candidate_id'], plan['proposal_revision'],
                                excluding_reversion=identifier)) != row['plan_json']:
                raise KnowledgeConflict('El estado reservado cambió durante la reversión')
            now = connection.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0]
            changes = ((plan['target_claim_id'], plan['restore_state'], 'ACTIVE', now, None, None),
                       (plan['successor_claim_id'], 'HISTORICAL', 'RETRACTED', None, now, plan['target_claim_id']))
            for claim_id, state, status, valid_from, valid_until, successor in changes:
                claim = connection.execute('SELECT * FROM knowledge_claims WHERE claim_id=?', (claim_id,)).fetchone()
                valid_from = valid_from or claim['valid_from']
                connection.execute('UPDATE knowledge_claims SET status=?,knowledge_state=?,valid_from=?,valid_until=?,'
                                   'superseded_by=?,revision=revision+1,updated_at=? WHERE claim_id=?',
                                   (status, state, valid_from, valid_until, successor, now, claim_id))
                connection.execute('INSERT INTO claim_state_history(claim_id,revision,from_state,to_state,valid_from,'
                                   'valid_until,superseded_by,actor,reason,candidate_id) VALUES (?,?,?,?,?,?,?,?,?,?)',
                                   (claim_id, claim['revision'] + 1, claim['knowledge_state'], state, valid_from,
                                    valid_until, successor, row['owner'],
                                    f"Reversión {identifier}: {row['reason']}", row['candidate_id']))
            patch = plan['patch']
            delta = len(patch['replacement']) - (patch['end'] - patch['start'])
            if delta:
                # Desplazar primero las posiciones que liberan sitio evita colisiones transitorias
                # entre dos citas idénticas en posiciones distintas (UNIQUE de fase 6).
                moved = [claim for claim in plan['claims'] if claim['status'] == 'ACTIVE'
                         and claim['claim_id'] != plan['successor_claim_id']
                         and claim['span_start'] >= patch['start'] + len(patch['replacement'])]
                for claim in sorted(moved, key=lambda c: c['span_start'], reverse=delta < 0):
                    connection.execute('UPDATE knowledge_claims SET span_start=span_start-?,span_end=span_end-?, '
                                       'updated_at=? WHERE claim_id=?', (delta, delta, now, claim['claim_id']))
            connection.execute('UPDATE notes SET content_hash=?,revision=revision+1,updated_at=? WHERE note_id=?',
                               (plan['result_hash'], now, plan['note_id']))
            connection.execute('INSERT INTO knowledge_reconciliation(note_id,state,expected_hash,observed_hash) '
                               "VALUES (?,'IN_SYNC',?,?) ON CONFLICT(note_id) DO UPDATE SET state='IN_SYNC',"
                               'expected_hash=excluded.expected_hash,observed_hash=excluded.observed_hash,checked_at=?',
                               (plan['note_id'], plan['result_hash'], plan['result_hash'], now))
            connection.execute("UPDATE update_candidates SET status='CONFLICT',blocked_reason='SUCCESSOR_REVERTED',"
                               'updated_at=? WHERE target_claim_id=? '
                               "AND status IN ('PENDING_COMPARISON','PENDING_REVIEW')",
                               (now, plan['successor_claim_id']))
            connection.execute("UPDATE maintenance_reversions SET status='APPLIED',finished_at=? WHERE reversion_id=?",
                               (now, identifier))
            connection.execute('INSERT INTO events(event_type,message,details_json) VALUES (?,?,?)',
                               ('MAINTENANCE_REVERSION_APPLIED', 'Reversión publicada conservando ambas revisiones',
                                encoded({'reversion_id': identifier, 'candidate_id': row['candidate_id'],
                                         'note_id': plan['note_id'], 'actor': row['owner']})))

    def conflict(self, identifier: str, code: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute("UPDATE maintenance_reversions SET status='CONFLICT',error_code=?,"
                               "finished_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
                               "WHERE reversion_id=? AND status='APPLYING'", (code, identifier))
            if not cursor.rowcount:
                return
            plan = json.loads(connection.execute('SELECT plan_json FROM maintenance_reversions WHERE reversion_id=?',
                                                 (identifier,)).fetchone()[0])
            connection.execute('INSERT INTO knowledge_reconciliation(note_id,state,expected_hash,observed_hash) '
                               "VALUES (?,'CONFLICT',?,NULL) ON CONFLICT(note_id) DO UPDATE SET state='CONFLICT',"
                               "observed_hash=NULL,checked_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                               (plan['note_id'], plan['base_hash']))
            connection.execute('INSERT INTO events(event_type,message,details_json) VALUES (?,?,?)',
                               ('MAINTENANCE_REVERSION_CONFLICT', 'La reversión requiere revisión',
                                encoded({'reversion_id': identifier, 'code': code})))

    def pending(self) -> list[dict]:
        with closing(self.database.connect(readonly=True)) as connection:
            return [self._record(row) for row in connection.execute(
                "SELECT * FROM maintenance_reversions WHERE status='APPLYING' ORDER BY created_at")]

    def list_records(self, *, actor: str | None, candidate_id: int | None = None,
                     limit: int = 100, offset: int = 0) -> list[dict]:
        from knowledge_orchestrator.repositories.knowledge_repository import KnowledgeRepository
        KnowledgeRepository._pagination(limit, offset)
        with closing(self.database.connect(readonly=True)) as connection:
            return [dict(row) for row in connection.execute(
                'SELECT reversion_id,candidate_id,owner,plan_hash,status,reason,error_code,created_at,confirmed_at,'
                'finished_at FROM maintenance_reversions WHERE (? IS NULL OR owner=?) '
                'AND (? IS NULL OR candidate_id=?) '
                'ORDER BY created_at DESC,reversion_id DESC LIMIT ? OFFSET ?',
                (actor, actor, candidate_id, candidate_id, limit, offset))]

    def audit(self, identifier: str) -> dict:
        """Consulta local de auditoría; no concede autorización para confirmar planes ajenos."""
        with closing(self.database.connect(readonly=True)) as connection:
            row = connection.execute('SELECT * FROM maintenance_reversions WHERE reversion_id=?',
                                      (identifier,)).fetchone()
            if row is None:
                raise ValueError('Reversión inexistente')
            return self._record(row)

    def publications(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        from knowledge_orchestrator.repositories.knowledge_repository import KnowledgeRepository
        KnowledgeRepository._pagination(limit, offset)
        with closing(self.database.connect(readonly=True)) as connection:
            return [dict(row) for row in connection.execute(
                'SELECT c.candidate_id,c.proposal_revision,c.target_note_id AS note_id,cap.title,c.applied_at,'
                'c.reviewed_by,c.automation_run_id,c.review_batch_id,'
                '(SELECT r.status FROM maintenance_reversions r WHERE r.candidate_id=c.candidate_id '
                "AND r.status IN ('APPLYING','APPLIED') LIMIT 1) AS reversion_status "
                'FROM update_candidates c JOIN notes n ON n.note_id=c.target_note_id '
                'JOIN captures cap ON cap.capture_id=n.capture_id '
                "WHERE c.status='APPLIED' ORDER BY c.applied_at DESC,c.candidate_id DESC LIMIT ? OFFSET ?",
                (limit, offset))]
