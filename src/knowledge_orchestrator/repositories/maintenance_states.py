"""Estados semánticos en la misma transacción que la comparación o aprobación."""
from __future__ import annotations

import json
import sqlite3

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict


def note_in_reversion(connection: sqlite3.Connection, note_id: int, *, excluding: str | None = None) -> bool:
    return connection.execute('SELECT 1 FROM maintenance_reversion_notes n '
        'JOIN maintenance_reversions r USING(reversion_id) WHERE n.note_id=? '
        "AND r.status='APPLYING' AND (? IS NULL OR r.reversion_id<>?)",
        (note_id, excluding, excluding)).fetchone() is not None


def claim_in_application(connection: sqlite3.Connection, claim_id: int, *,
                         excluding_candidate: int | None = None, excluding_reversion: str | None = None) -> bool:
    """La intención reserva la nota destino y toda la cadena de evidencia leída."""
    claim = connection.execute('SELECT note_id FROM knowledge_claims WHERE claim_id=?', (claim_id,)).fetchone()
    if claim and note_in_reversion(connection, claim['note_id'], excluding=excluding_reversion):
        return True
    return connection.execute(
        'WITH RECURSIVE origins(candidate_id,claim_id,parent_id) AS ('
        'SELECT c.candidate_id,k.claim_id,k.derived_from_claim_id FROM update_candidates c '
        "JOIN knowledge_claims k ON k.claim_id=c.new_claim_id WHERE c.status='APPLYING' "
        'AND (? IS NULL OR c.candidate_id<>?) UNION '
        'SELECT o.candidate_id,k.claim_id,k.derived_from_claim_id FROM origins o '
        'JOIN knowledge_claims k ON k.claim_id=o.parent_id) '
        'SELECT 1 FROM origins WHERE claim_id=? UNION ALL '
        'SELECT 1 FROM update_candidates c JOIN knowledge_claims k ON k.note_id=c.target_note_id '
        "WHERE c.status='APPLYING' AND (? IS NULL OR c.candidate_id<>?) AND k.claim_id=? LIMIT 1",
        (excluding_candidate, excluding_candidate, claim_id,
         excluding_candidate, excluding_candidate, claim_id),
    ).fetchone() is not None


def record_review_state(connection: sqlite3.Connection, claim_id: int, state: str, *, actor: str,
                        reason: str, candidate_id: int | None) -> None:
    row = connection.execute('SELECT * FROM knowledge_claims WHERE claim_id=?', (claim_id,)).fetchone()
    if row is None or row['status'] != 'ACTIVE' or row['manual_lock'] or row['knowledge_state'] == state:
        return
    if claim_in_application(connection, claim_id, excluding_candidate=candidate_id):
        raise KnowledgeConflict('El claim participa en otra aplicación pendiente')
    connection.execute('UPDATE knowledge_claims SET knowledge_state=?,revision=revision+1,'
                       "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE claim_id=?", (state, claim_id))
    connection.execute('INSERT INTO claim_state_history(claim_id,revision,from_state,to_state,valid_from,actor,'
                       'reason,candidate_id) VALUES (?,?,?,?,?,?,?,?)',
                       (claim_id, row['revision'] + 1, row['knowledge_state'], state, row['valid_from'],
                        actor, reason, candidate_id))
    connection.execute('INSERT INTO events(event_type,message,details_json) VALUES (?,?,?)',
                       ('CLAIM_STATE_CHANGED', 'Estado de revisión del conocimiento actualizado',
                        json.dumps({'claim_id': claim_id, 'candidate_id': candidate_id, 'actor': actor,
                                    'to_state': state})))
