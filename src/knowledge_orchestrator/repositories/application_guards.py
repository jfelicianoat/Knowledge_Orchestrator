"""Guardas compartidas por simulación y aplicación, sin efectos laterales."""
from __future__ import annotations

import json
import sqlite3

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.repositories.knowledge_repository import KnowledgeRepository
from knowledge_orchestrator.repositories.maintenance_states import note_in_reversion


def check_application(connection: sqlite3.Connection, candidate_id: int, *, base_hash: str,
                      patch_json: str, expected_revision: int | None) -> sqlite3.Row:
    row = connection.execute(
        'SELECT c.*, k.manual_lock, k.status AS claim_status,n.status AS note_status,n.content_hash '
        'FROM update_candidates c JOIN knowledge_claims k ON k.claim_id=c.target_claim_id '
        'JOIN notes n ON n.note_id=c.target_note_id WHERE c.candidate_id=?',
        (candidate_id,),
    ).fetchone()
    if row is None or row["status"] != "PENDING_REVIEW":
        raise ValueError("El candidato no se puede aprobar")
    if note_in_reversion(connection, row['target_note_id']):
        raise KnowledgeConflict('Una reversión está usando la nota objetivo')
    origins = connection.execute('WITH RECURSIVE origins(claim_id,note_id,parent_id) AS ('
        'SELECT claim_id,note_id,derived_from_claim_id FROM knowledge_claims WHERE claim_id=? UNION '
        'SELECT k.claim_id,k.note_id,k.derived_from_claim_id FROM knowledge_claims k '
        'JOIN origins o ON k.claim_id=o.parent_id) SELECT note_id FROM origins', (row['new_claim_id'],)).fetchall()
    if any(note_in_reversion(connection, origin['note_id']) for origin in origins):
        raise KnowledgeConflict('Una reversión está usando la evidencia de la propuesta')
    if (expected_revision is not None and row['proposal_revision'] != expected_revision) \
            or row['patch_json'] != patch_json:
        raise KnowledgeConflict('La propuesta cambió durante la aprobación')
    if row["claim_status"] != "ACTIVE":
        raise ValueError("El claim objetivo ya no está activo")
    if row['note_status'] != 'PUBLISHED' or row['content_hash'] != base_hash:
        raise KnowledgeConflict('La revisión documental cambió durante la aprobación')
    if bool(row["manual_lock"]) or row["blocked_reason"]:
        raise ValueError("El claim objetivo está bloqueado manualmente")
    successor = connection.execute(
        'SELECT k.*, n.status AS note_status FROM knowledge_claims k '
        'JOIN notes n ON n.note_id = k.note_id WHERE k.claim_id = ?', (row['new_claim_id'],),
    ).fetchone()
    if successor is None or successor['status'] != 'ACTIVE' or successor['manual_lock'] \
            or successor['note_status'] != 'PUBLISHED':
        raise ValueError('La evidencia sucesora ya no está disponible como vigente')
    if not connection.execute('SELECT 1 FROM knowledge_claims k WHERE k.claim_id=? AND '
                              + KnowledgeRepository.provenance_filter(), (row['new_claim_id'],)).fetchone():
        raise KnowledgeConflict('La procedencia de la evidencia requiere revisión')
    if connection.execute(
        "SELECT 1 FROM update_candidates WHERE relation='CONTRADICTS' AND candidate_id<>? "
        "AND status IN ('PENDING_REVIEW','CONFLICT','APPLYING') "
        'AND (target_claim_id IN (?,?) OR new_claim_id IN (?,?))',
        (candidate_id, row['target_claim_id'], row['new_claim_id'],
         row['target_claim_id'], row['new_claim_id']),
    ).fetchone():
        raise KnowledgeConflict('Hay otras contradicciones pendientes sobre estos claims')
    if row['base_hash'] != base_hash:
        raise ValueError('La nota cambió desde el diff')
    if connection.execute(
        'WITH RECURSIVE reads(candidate_id,claim_id,note_id,parent_id,depth) AS ('
        'SELECT c.candidate_id,k.claim_id,k.note_id,k.derived_from_claim_id,1 FROM update_candidates c '
        "JOIN knowledge_claims k ON k.claim_id=c.new_claim_id WHERE c.status='APPLYING' OR c.candidate_id=? "
        'UNION ALL SELECT r.candidate_id,k.claim_id,k.note_id,k.derived_from_claim_id,r.depth+1 '
        'FROM reads r JOIN knowledge_claims k ON k.claim_id=r.parent_id WHERE r.depth<100) '
        "SELECT 1 FROM update_candidates c WHERE c.status='APPLYING' AND c.candidate_id<>? AND "
        '(c.target_note_id=? OR c.target_note_id IN (SELECT note_id FROM reads WHERE candidate_id=?) '
        'OR EXISTS (SELECT 1 FROM reads r WHERE r.candidate_id=c.candidate_id AND r.note_id=?))',
        (candidate_id, candidate_id, row['target_note_id'], candidate_id, row['target_note_id']),
    ).fetchone():
        raise KnowledgeConflict('Otra aplicación está usando una de las notas como evidencia')
    if connection.execute(
        "SELECT 1 FROM update_candidates WHERE target_note_id = ? AND status = 'APPLYING' "
        'AND candidate_id <> ?', (row['target_note_id'], candidate_id),
    ).fetchone():
        raise ValueError('Ya existe una aplicación pendiente sobre esta nota')
    patch = json.loads(patch_json)
    if connection.execute(
        "SELECT 1 FROM knowledge_claims WHERE note_id = ? AND status = 'ACTIVE' AND manual_lock = 1 "
        'AND span_start < ? AND span_end > ?', (row['target_note_id'], patch['end'], patch['start']),
    ).fetchone():
        raise ValueError('El cambio afecta un claim bloqueado manualmente')
    if connection.execute(
        "SELECT 1 FROM knowledge_claims WHERE note_id = ? AND status = 'ACTIVE' AND claim_id <> ? "
        'AND span_start < ? AND span_end > ?',
        (row['target_note_id'], row['target_claim_id'], patch['end'], patch['start']),
    ).fetchone():
        raise ValueError('El cambio afecta otro claim solapado; requiere una propuesta conjunta')
    if connection.execute(
        'SELECT 1 FROM knowledge_claims WHERE note_id=? AND span_start=? AND span_end=? '
        'AND normalized_statement=?', (row['target_note_id'], patch['start'] + patch.get('current_offset', 0),
                                      patch['start'] + patch.get('current_offset', 0)
                                      + len(patch.get('source_quote', patch['replacement'])),
                                      successor['normalized_statement']),
    ).fetchone():
        raise ValueError('La formulación ya está registrada en ese span; revisar como apoyo sin reemplazo')
    return row
