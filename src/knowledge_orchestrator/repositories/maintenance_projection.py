"""Proyección de evidencia existente en la nota actualizada, dentro de su commit SQLite."""
from __future__ import annotations

import sqlite3

from knowledge_orchestrator.repositories.knowledge_repository import register_claim


def project_successor(connection: sqlite3.Connection, candidate: sqlite3.Row, patch: dict) -> int:
    witness = connection.execute('SELECT * FROM knowledge_claims WHERE claim_id=?',
                                 (candidate['new_claim_id'],)).fetchone()
    start = patch['start'] + patch.get('current_offset', 0)
    quote = patch.get('source_quote', patch['replacement'])
    end = start + len(quote)
    topic_id = connection.execute('SELECT topic_id FROM notes WHERE note_id=?',
                                  (candidate['target_note_id'],)).fetchone()[0]
    cursor = connection.execute(
        'INSERT INTO knowledge_claims(note_id,source_capture_id,topic_id,statement,normalized_statement,'
        'claim_type,volatility,observed_at,source_date,span_start,span_end,entities_json,derived_from_claim_id) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (candidate['target_note_id'], witness['source_capture_id'], topic_id, quote.strip(),
         witness['normalized_statement'], witness['claim_type'], witness['volatility'], witness['observed_at'],
         witness['source_date'], start, end, witness['entities_json'], witness['claim_id']))
    claim_id = cursor.lastrowid
    assert claim_id is not None
    # Evidence points to its original source and offsets; claim offsets describe its new documentary location.
    connection.execute(
        'INSERT INTO evidence_links(claim_id,source_capture_id,source_note_id,quote,span_start,span_end,'
        'source_path,source_content_hash) SELECT ?,source_capture_id,source_note_id,quote,span_start,span_end,'
        'source_path,source_content_hash FROM evidence_links WHERE claim_id=?', (claim_id, witness['claim_id']))
    register_claim(connection, claim_id, actor=candidate['reviewed_by'] or 'human:review',
                   reason='Proyección de evidencia original tras aprobación')
    connection.execute('INSERT INTO claim_embeddings(claim_id,model,dimensions,vector_json) '
                       'SELECT ?,model,dimensions,vector_json FROM claim_embeddings WHERE claim_id=?',
                       (claim_id, witness['claim_id']))
    connection.execute('UPDATE update_candidates SET applied_successor_id=? WHERE candidate_id=?',
                       (claim_id, candidate['candidate_id']))
    return claim_id
