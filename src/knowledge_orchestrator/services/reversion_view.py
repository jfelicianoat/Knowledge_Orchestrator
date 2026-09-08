"""Vista de revisión compartida por API/UI, sin rutas ni filas internas de la base de datos."""
from __future__ import annotations


def reversion_view(record: dict) -> dict:
    plan = record['plan']
    result = {key: record[key] for key in ('reversion_id', 'candidate_id', 'owner', 'plan_hash', 'status', 'reason',
                                          'error_code', 'created_at', 'confirmed_at', 'finished_at')}
    result['plan'] = {key: plan[key] for key in ('note_id', 'target_claim_id', 'successor_claim_id',
                                               'proposal_revision',
                                               'restore_state', 'base_hash', 'result_hash', 'before', 'proposed',
                                               'publication_authorized')}
    result['plan']['evidence'] = [{key: evidence[key] for key in (
        'evidence_id', 'claim_id', 'source_capture_id', 'source_note_id', 'quote', 'span_start', 'span_end',
        'source_content_hash')} for evidence in plan['evidence']]
    return result
