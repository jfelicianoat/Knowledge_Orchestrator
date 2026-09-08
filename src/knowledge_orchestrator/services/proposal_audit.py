"""Consulta local de trazabilidad, sin mutaciones ni payloads privados del Broker."""
from __future__ import annotations

import json
from contextlib import closing

from knowledge_orchestrator.repositories.database import Database


class ProposalAuditReader:
    page_size = 100

    def __init__(self, database: Database) -> None:
        self.database = database

    def read(self, candidate_id: int, *, offset: int = 0, revision: int | None = None) -> dict:
        if type(offset) is not int or offset < 0:
            raise ValueError('Página de revisiones inválida')
        if revision is not None and (type(revision) is not int or revision < 1):
            raise ValueError('Revisión de propuesta inválida')
        with closing(self.database.connect(readonly=True)) as connection:
            connection.execute('BEGIN')
            row = connection.execute(
                'SELECT candidate_id,status,proposal_revision,target_note_id,target_claim_id,new_claim_id,'
                'created_at,updated_at,reviewed_at,applied_at,reviewed_by,applied_successor_id,'
                'review_batch_id,automation_run_id FROM update_candidates WHERE candidate_id=?',
                (candidate_id,)).fetchone()
            if row is None:
                raise LookupError('La propuesta no existe')
            candidate = dict(row)
            total = connection.execute('SELECT count(*) FROM maintenance_proposal_versions WHERE candidate_id=?',
                                       (candidate_id,)).fetchone()[0]
            if revision is not None:
                if connection.execute('SELECT 1 FROM maintenance_proposal_versions WHERE candidate_id=? AND revision=?',
                                      (candidate_id, revision)).fetchone() is None:
                    raise ValueError('La revisión no pertenece a esta propuesta')
                newer = connection.execute('SELECT count(*) FROM maintenance_proposal_versions '
                    'WHERE candidate_id=? AND revision>?', (candidate_id, revision)).fetchone()[0]
                offset = (newer // self.page_size) * self.page_size
            offset = min(offset, max(0, ((total - 1) // self.page_size) * self.page_size))
            versions = [dict(item) for item in connection.execute(
                'SELECT revision,actor,created_at FROM maintenance_proposal_versions WHERE candidate_id=? '
                'ORDER BY revision DESC LIMIT ? OFFSET ?', (candidate_id, self.page_size, offset))]
            selected = next((item for item in versions if item['revision'] == revision), None) if revision else (
                versions[0] if versions else None)
            if revision is not None and selected is None:
                raise ValueError('La revisión no pertenece a esta página de la propuesta')
            snapshot = None
            if selected:
                snapshot = json.loads(connection.execute(
                    'SELECT snapshot_json FROM maintenance_proposal_versions WHERE candidate_id=? AND revision=?',
                    (candidate_id, selected['revision'])).fetchone()[0])
            policy = connection.execute(
                'SELECT r.run_id,r.simulation_id,r.policy_id,r.policy_revision,r.status,r.created_at,r.completed_at,'
                'd.actor AS authorized_by,d.created_at AS authorized_at,d.reviewed_simulation_id '
                'FROM automation_runs r LEFT JOIN automation_policy_decisions d ON d.policy_id=r.policy_id '
                'AND d.state_revision=r.policy_state_revision AND d.revision=r.policy_revision '
                'WHERE r.run_id=?', (candidate['automation_run_id'],)).fetchone()
            batch = connection.execute('SELECT batch_id,owner,status,confirmed_at,completed_at FROM review_batches '
                                       'WHERE batch_id=?', (candidate['review_batch_id'],)).fetchone()
            previous = connection.execute('SELECT revision,content_hash,created_at FROM note_revisions '
                'WHERE candidate_id=? ORDER BY revision DESC LIMIT 1', (candidate_id,)).fetchone()
            reversion = connection.execute('SELECT reversion_id,status,owner,confirmed_at,finished_at '
                "FROM maintenance_reversions WHERE candidate_id=? AND status IN ('APPLYING','APPLIED') "
                'ORDER BY created_at DESC LIMIT 1', (candidate_id,)).fetchone()
            return {'candidate': candidate, 'versions': versions, 'selected': selected, 'snapshot': snapshot,
                    'offset': offset, 'total': total,
                    'policy': dict(policy) if policy else None, 'batch': dict(batch) if batch else None,
                    'previous_note': dict(previous) if previous else None,
                    'reversion': dict(reversion) if reversion else None}
