"""Estado exacto que puede compensarse sin restaurar ciegamente toda una base de datos."""
from __future__ import annotations

import hashlib
import json
import sqlite3

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.repositories.maintenance_states import claim_in_application


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def encoded(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def snapshot(connection: sqlite3.Connection, candidate_id: int, expected_revision: int, *,
             excluding_reversion: str | None = None) -> dict:
    candidate = connection.execute('SELECT * FROM update_candidates WHERE candidate_id=?',
                                   (candidate_id,)).fetchone()
    if candidate is None or candidate['status'] != 'APPLIED' or not candidate['applied_successor_id']:
        raise KnowledgeConflict('La reversión requiere una propuesta aplicada con sucesor registrado')
    if candidate['proposal_revision'] != expected_revision:
        raise KnowledgeConflict('La revisión de la propuesta cambió')
    if connection.execute("SELECT 1 FROM maintenance_reversions WHERE candidate_id=? "
                           "AND status IN ('APPLYING','APPLIED') AND (? IS NULL OR reversion_id<>?)",
                           (candidate_id, excluding_reversion, excluding_reversion)).fetchone():
        raise KnowledgeConflict('La propuesta ya tiene una reversión iniciada o aplicada')
    note = connection.execute('SELECT * FROM notes WHERE note_id=?', (candidate['target_note_id'],)).fetchone()
    if note['status'] != 'PUBLISHED' or note['content_hash'] != candidate['result_hash']:
        raise KnowledgeConflict('La nota tiene otra revisión; requiere una propuesta nueva')
    revision = connection.execute('SELECT * FROM note_revisions WHERE note_id=? '
                                   "AND reason='SEMANTIC_UPDATE' AND candidate_id=? ORDER BY revision DESC LIMIT 1",
                                   (note['note_id'], candidate_id)).fetchone()
    if revision is None or revision['content_hash'] != candidate['base_hash'] \
            or text_hash(revision['content_text']) != revision['content_hash']:
        raise KnowledgeConflict('No se conserva una revisión anterior verificable')
    # Una reversión anterior no autoriza deshacer publicaciones intermedias aun si el texto coincide.
    latest = connection.execute('SELECT * FROM note_revisions WHERE note_id=? ORDER BY revision DESC LIMIT 1',
                                 (note['note_id'],)).fetchone()
    if latest['note_revision_id'] != revision['note_revision_id'] and not (
        excluding_reversion and latest['reason'] == f'REVERSION:{excluding_reversion}'
    ):
        raise KnowledgeConflict('Hay publicaciones posteriores a la actualización')
    claims = [dict(row) for row in connection.execute('SELECT * FROM knowledge_claims WHERE note_id=? '
                                                       'ORDER BY claim_id', (note['note_id'],))]
    target = next(row for row in claims if row['claim_id'] == candidate['target_claim_id'])
    successor = next(row for row in claims if row['claim_id'] == candidate['applied_successor_id'])
    if any(row['manual_lock'] for row in claims):
        raise KnowledgeConflict('MANUAL_LOCK: la nota contiene un claim bloqueado')
    if target['status'] != 'SUPERSEDED' or target['superseded_by'] != successor['claim_id'] \
            or successor['status'] != 'ACTIVE' or successor['knowledge_state'] != 'CURRENT' \
            or successor['revision'] != 1:
        raise KnowledgeConflict('Los claims tienen decisiones posteriores; requieren revisión individual')
    history = [dict(row) for row in connection.execute('SELECT * FROM claim_state_history WHERE claim_id=? '
                                                       'ORDER BY revision DESC LIMIT 2', (target['claim_id'],))]
    if len(history) != 2 or history[0]['candidate_id'] != candidate_id \
            or history[0]['revision'] != target['revision']:
        raise KnowledgeConflict('El historial no acredita la transición que se quiere revertir')
    previous_state = history[1]['to_state']
    if previous_state not in ('CURRENT', 'DISPUTED', 'UNCERTAIN', 'REVIEW_REQUIRED'):
        raise KnowledgeConflict('El claim anterior no era revisable como activo')
    if connection.execute('WITH RECURSIVE dependents(claim_id,note_id,status) AS ('
        'SELECT c.claim_id,c.note_id,c.status FROM knowledge_claims c JOIN knowledge_claims p '
        'ON c.derived_from_claim_id=p.claim_id WHERE p.note_id=? UNION '
        'SELECT c.claim_id,c.note_id,c.status FROM knowledge_claims c JOIN dependents d '
        'ON c.derived_from_claim_id=d.claim_id) SELECT 1 FROM dependents '
        "WHERE status='ACTIVE' AND (note_id<>? OR claim_id<>?)",
        (note['note_id'], note['note_id'], successor['claim_id'])).fetchone():
        raise KnowledgeConflict('Hay conocimiento derivado de la nota; no se revierte en cascada')
    if connection.execute("SELECT 1 FROM update_candidates WHERE candidate_id<>? AND relation='CONTRADICTS' "
                           "AND status IN ('PENDING_REVIEW','CONFLICT','APPLYING') "
                           'AND (target_claim_id IN (?,?) OR new_claim_id IN (?,?))',
                           (candidate_id, target['claim_id'], successor['claim_id'],
                            target['claim_id'], successor['claim_id'])).fetchone():
        raise KnowledgeConflict('Hay contradicciones posteriores pendientes')
    original = revision['content_text']
    patch = json.loads(candidate['patch_json'])
    start, end = patch['start'], patch['end']
    if original[start:end] != patch['old']:
        raise KnowledgeConflict('El patch no coincide con la revisión anterior')
    published = original[:start] + patch['replacement'] + original[end:]
    if text_hash(published) != candidate['result_hash']:
        raise KnowledgeConflict('El resultado publicado no se puede reconstruir')
    delta = len(patch['replacement']) - (end - start)
    for active in claims:
        if active['status'] != 'ACTIVE' or active['claim_id'] == successor['claim_id']:
            continue
        left, right = active['span_start'], active['span_end']
        if left < start + len(patch['replacement']) and right > start:
            raise KnowledgeConflict('Hay otro claim sobre el contenido que se quiere revertir')
        shift = delta if left >= start + len(patch['replacement']) else 0
        if published[left:right] != original[left-shift:right-shift]:
            raise KnowledgeConflict('La reversión alteraría evidencia de otro claim')
    positions: set[tuple[int, int, str]] = set()
    for row in claims:
        shift = delta if row['status'] == 'ACTIVE' and row['claim_id'] != successor['claim_id'] \
            and row['span_start'] >= start + len(patch['replacement']) else 0
        position = (row['span_start'] - shift, row['span_end'] - shift, row['normalized_statement'])
        if position in positions:
            raise KnowledgeConflict('Las posiciones restauradas coinciden con otro claim; requiere revisión')
        positions.add(position)
    origins, evidence, notes = [], [], {note['note_id']: dict(note)}
    claim: dict | None = target
    seen: set[int] = set()
    while claim:
        if claim['claim_id'] in seen or len(seen) >= 100:
            raise KnowledgeConflict('Cadena de procedencia inválida')
        seen.add(claim['claim_id'])
        if claim is not target and (claim['status'] != 'ACTIVE' or claim['knowledge_state'] != 'CURRENT'
                                     or claim['manual_lock']):
            raise KnowledgeConflict('La evidencia anterior ya no está disponible como vigente')
        origins.append(dict(claim))
        links = [dict(row) for row in connection.execute('SELECT * FROM evidence_links WHERE claim_id=? '
                                                         'ORDER BY evidence_id', (claim['claim_id'],))]
        if not links:
            raise KnowledgeConflict('El claim anterior no conserva evidencia')
        evidence.extend(links)
        for identifier in {claim['note_id'], *(link['source_note_id'] for link in links)}:
            source = connection.execute('SELECT * FROM notes WHERE note_id=?', (identifier,)).fetchone()
            if source is None or source['status'] != 'PUBLISHED':
                raise KnowledgeConflict('Una nota de evidencia no está publicada')
            notes[source['note_id']] = dict(source)
        parent = claim['derived_from_claim_id']
        claim = dict(connection.execute('SELECT * FROM knowledge_claims WHERE claim_id=?', (parent,)).fetchone()) \
            if parent else None
    for row in claims + origins:
        if claim_in_application(connection, row['claim_id'], excluding_reversion=excluding_reversion):
            raise KnowledgeConflict('Hay otra publicación o reversión pendiente sobre la evidencia')
    for identifier in notes:
        if connection.execute('SELECT 1 FROM maintenance_reversion_notes n '
                               'JOIN maintenance_reversions r USING(reversion_id) WHERE n.note_id=? '
                               "AND r.status='APPLYING' AND (? IS NULL OR r.reversion_id<>?)",
                               (identifier, excluding_reversion, excluding_reversion)).fetchone():
            raise KnowledgeConflict('Otra reversión reserva una de las notas')
    return {'candidate_id': candidate_id, 'proposal_revision': expected_revision, 'note_id': note['note_id'],
            'target_claim_id': target['claim_id'], 'successor_claim_id': successor['claim_id'],
            'restore_state': previous_state, 'base_hash': candidate['result_hash'],
            'result_hash': candidate['base_hash'], 'before': published, 'proposed': original,
            'patch': patch, 'claims': claims, 'origins': origins, 'evidence': evidence,
            'notes': [notes[key] for key in sorted(notes)], 'revision_id': revision['note_revision_id'],
            'publication_authorized': False}
