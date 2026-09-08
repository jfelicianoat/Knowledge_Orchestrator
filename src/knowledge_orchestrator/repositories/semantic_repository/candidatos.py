"""Candidatos de actualización: propuesta, comparación y aplicación.

`prepare_application` y `mark_applied` son la parte que toca ficheros del
vault: se hacen contra un temporal y con hash esperado, para que un fallo a
mitad no deje una nota a medias.
"""
from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

from knowledge_orchestrator.domain.knowledge import KnowledgeConflict
from knowledge_orchestrator.domain.semantic_models import (
    ComparisonDecision,
    KnowledgeClaim,
    UpdateCandidate,
)
from knowledge_orchestrator.repositories.application_guards import check_application
from knowledge_orchestrator.repositories.automation_guards import reserve_policy_application
from knowledge_orchestrator.repositories.knowledge_repository import record_supersession
from knowledge_orchestrator.repositories.maintenance_projection import project_successor
from knowledge_orchestrator.repositories.maintenance_states import record_review_state
from knowledge_orchestrator.repositories.semantic_repository.afirmaciones import AfirmacionesMixin
from knowledge_orchestrator.repositories.semantic_repository.filas import _candidate


class CandidatosMixin(AfirmacionesMixin):
    """Ciclo de vida de un candidato de actualización."""

    @staticmethod
    def _audit_candidate_transition(connection, candidate_id: int, previous: str | None) -> None:
        row = connection.execute(
            'SELECT candidate_id,target_note_id,target_claim_id,new_claim_id,proposal_revision,status,'
            'reviewed_by,review_batch_id,automation_run_id,blocked_reason FROM update_candidates WHERE candidate_id=?',
            (candidate_id,)).fetchone()
        details = dict(row)
        reason = details.pop('blocked_reason')
        known_reasons = {'MANUAL_LOCK', 'TARGET_SUPERSEDED', 'NOTE_CHANGED_AFTER_DIFF', 'EVIDENCE_CHANGED_AFTER_DIFF',
                         'NOTE_CHANGED_DURING_APPLICATION', 'CONTENT_CHANGED_DURING_APPLICATION',
                         'INCOMPLETE_APPLICATION_INTENT', 'NOTE_CHANGED_DURING_RECOVERY',
                         'CONTENT_CHANGED_DURING_RECOVERY'}
        details.update(from_status=previous, reason_code=reason if reason in known_reasons else 'UNSPECIFIED')
        connection.execute('INSERT INTO events(event_type,message,details_json) VALUES (?,?,?)',
                           ('MAINTENANCE_CANDIDATE_STATE_CHANGED', 'Transición de propuesta de conocimiento',
                            json.dumps(details)))

    def create_candidate(
        self,
        target: KnowledgeClaim,
        new_claim: KnowledgeClaim,
        *,
        retrieval_reason: str,
    ) -> UpdateCandidate:
        blocked = "MANUAL_LOCK" if target.manual_lock else None
        with self.database.transaction(immediate=True) as connection:
            inserted = connection.execute(
                "INSERT INTO update_candidates(target_note_id, target_claim_id, new_claim_id, "
                "retrieval_reason, blocked_reason) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(target_claim_id, new_claim_id) DO NOTHING",
                (target.note_id, target.claim_id, new_claim.claim_id, retrieval_reason, blocked),
            )
            row = connection.execute(
                "SELECT * FROM update_candidates WHERE target_claim_id = ? AND new_claim_id = ?",
                (target.claim_id, new_claim.claim_id),
            ).fetchone()
            if inserted.rowcount:
                self._audit_candidate_transition(connection, row['candidate_id'], None)
            return _candidate(row)

    def get_candidate(self, candidate_id: int) -> UpdateCandidate | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT * FROM update_candidates WHERE candidate_id = ?", (candidate_id,)
            ).fetchone()
            return _candidate(row) if row else None

    def list_candidates(self, *statuses: str) -> list[UpdateCandidate]:
        parameters: tuple[object, ...] = tuple(statuses)
        where = ""
        if statuses:
            where = " WHERE status IN (" + ",".join("?" for _ in statuses) + ")"
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM update_candidates" + where + " ORDER BY candidate_id",
                parameters,
            ).fetchall()
            return [_candidate(row) for row in rows]

    def record_comparison(
        self,
        candidate_id: int,
        decision: ComparisonDecision,
        *,
        patch_json: str | None,
        diff_text: str | None,
        base_hash: str | None = None,
        assessment: dict | None = None,
        expected_revision: int | None = None,
        actor: str = 'broker:comparison',
    ) -> UpdateCandidate:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT c.*, k.manual_lock, k.status AS claim_status FROM update_candidates c "
                "JOIN knowledge_claims k ON k.claim_id = c.target_claim_id WHERE c.candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            permitted = {'PENDING_COMPARISON'} if expected_revision is None else \
                {'PENDING_COMPARISON', 'PENDING_REVIEW', 'CONFLICT'}
            if row is None or row['status'] not in permitted:
                raise ValueError("El candidato no está pendiente de comparación")
            if expected_revision is not None and row['proposal_revision'] != expected_revision:
                raise KnowledgeConflict('La propuesta cambió desde que se abrió')
            if row["claim_status"] != "ACTIVE":
                raise ValueError("El claim objetivo ya no está activo")
            blocked = 'MANUAL_LOCK' if bool(row['manual_lock']) else None
            if decision.relation == 'CONTRADICTS':
                for claim_id in (row['target_claim_id'], row['new_claim_id']):
                    record_review_state(connection, claim_id, 'DISPUTED', actor=actor,
                                        reason='Contradicción entre evidencias; requiere revisión humana',
                                        candidate_id=candidate_id)
            elif decision.relation == 'UNCERTAIN':
                record_review_state(connection, row['new_claim_id'], 'UNCERTAIN', actor=actor,
                                    reason='La comparación no pudo establecer la relación', candidate_id=candidate_id)
            reviewable = decision.relation in {'EXTENDS', 'CONTRADICTS', 'SUPERSEDES', 'UNCERTAIN'}
            status = "PENDING_REVIEW" if reviewable else "REJECTED"
            connection.execute(
                "UPDATE update_candidates SET relation = ?, confidence = ?, impact = ?, rationale = ?, "
                "replacement_text = ?, patch_json = ?, diff_text = ?, base_hash = ?, blocked_reason = ?, status = ?, "
                'proposal_revision=proposal_revision+1, '
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE candidate_id = ?",
                (
                    decision.relation, decision.confidence, decision.impact, decision.rationale,
                    decision.replacement_text, patch_json, diff_text, base_hash, blocked, status, candidate_id,
                ),
            )
            snapshot = assessment or {'candidate_id': candidate_id, 'rationale': decision.rationale,
                                      'patch': json.loads(patch_json) if patch_json else None}
            connection.execute('INSERT INTO maintenance_proposal_versions(candidate_id,revision,snapshot_json,actor) '
                               'VALUES (?,?,?,?)', (candidate_id, row['proposal_revision'] + 1,
                                                    json.dumps(snapshot, ensure_ascii=False), actor))
            connection.execute('INSERT INTO events(event_type,message,details_json) VALUES (?,?,?)',
                               ('MAINTENANCE_PROPOSAL_REVISED', 'Propuesta fundamentada registrada', json.dumps({
                                   'candidate_id': candidate_id, 'revision': row['proposal_revision'] + 1,
                                   'actor': actor})))
            return _candidate(connection.execute(
                "SELECT * FROM update_candidates WHERE candidate_id = ?", (candidate_id,)
            ).fetchone())

    def inspect_application(self, candidate_id: int, *, base_hash: str, patch_json: str,
                            expected_revision: int) -> None:
        with closing(self.database.connect(readonly=True)) as connection:
            connection.execute('BEGIN')
            check_application(connection, candidate_id, base_hash=base_hash,
                              patch_json=patch_json, expected_revision=expected_revision)

    def prepare_application(
        self,
        candidate_id: int,
        *,
        current_content: str,
        base_hash: str,
        result_hash: str,
        temp_path: Path,
        patch_json: str,
        expected_revision: int | None = None,
        actor: str = 'human:review',
        review_batch_id: str | None = None,
        automation_run_id: str | None = None,
    ) -> UpdateCandidate:
        with self.database.transaction(immediate=True) as connection:
            row = check_application(connection, candidate_id, base_hash=base_hash,
                                    patch_json=patch_json, expected_revision=expected_revision)
            if automation_run_id is not None:
                if review_batch_id is not None:
                    raise ValueError('Una aplicación no puede atribuirse a lote humano y política a la vez')
                reserve_policy_application(connection, row, run_id=automation_run_id, actor=actor)
            if review_batch_id is not None and not connection.execute(
                'SELECT 1 FROM review_batches b JOIN review_batch_items i USING(batch_id) '
                "WHERE b.batch_id=? AND b.owner=? AND b.status='RUNNING' AND i.status='RUNNING' "
                'AND i.candidate_id=? AND i.expected_revision=?',
                (review_batch_id, actor, candidate_id, row['proposal_revision']),
            ).fetchone():
                raise KnowledgeConflict('El lote no autoriza esta revisión de propuesta')
            if row["status"] != "APPLYING":
                revision = int(connection.execute(
                    "SELECT COALESCE(MAX(revision), 0) + 1 FROM note_revisions WHERE note_id = ?",
                    (row["target_note_id"],),
                ).fetchone()[0])
                connection.execute(
                    "INSERT INTO note_revisions(note_id, candidate_id, revision, content_text, content_hash, reason) "
                    "VALUES (?, ?, ?, ?, ?, 'SEMANTIC_UPDATE')",
                    (row["target_note_id"], candidate_id, revision, current_content, base_hash),
                )
            connection.execute(
                "UPDATE update_candidates SET status = 'APPLYING', base_hash = ?, result_hash = ?, temp_path = ?, "
                'patch_json = ?, reviewed_by=?, review_batch_id=?, automation_run_id=?, '
                "reviewed_at = COALESCE(reviewed_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE candidate_id = ?",
                (base_hash, result_hash, str(temp_path), patch_json, actor, review_batch_id, automation_run_id,
                 candidate_id),
            )
            if row['status'] != 'APPLYING':
                self._audit_candidate_transition(connection, candidate_id, row['status'])
            return _candidate(connection.execute(
                "SELECT * FROM update_candidates WHERE candidate_id = ?", (candidate_id,)
            ).fetchone())

    def mark_applied(self, candidate_id: int) -> None:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT * FROM update_candidates "
                "WHERE candidate_id = ? AND status = 'APPLYING'",
                (candidate_id,),
            ).fetchone()
            if row is None:
                return
            patch = json.loads(row['patch_json'])
            record_review_state(connection, row['new_claim_id'], 'CURRENT',
                                actor=row['reviewed_by'] or 'human:review',
                                reason='Evidencia seleccionada explícitamente al aprobar la propuesta',
                                candidate_id=candidate_id)
            successor_id = project_successor(connection, row, patch)
            record_supersession(connection, candidate_id, successor_id=successor_id)
            connection.execute(
                "UPDATE update_candidates SET status = 'APPLIED', temp_path = NULL, applied_at = "
                "strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE candidate_id = ?",
                (candidate_id,),
            )
            connection.execute(
                "UPDATE notes SET content_hash = (SELECT result_hash FROM update_candidates WHERE candidate_id = ?), "
                "revision=revision+1,updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE note_id = ?",
                (candidate_id, row["target_note_id"]),
            )
            conflicting = connection.execute(
                "SELECT candidate_id,status FROM update_candidates WHERE target_claim_id=? AND candidate_id<>? "
                "AND status IN ('PENDING_COMPARISON', 'PENDING_REVIEW', 'APPROVED')",
                (row['target_claim_id'], candidate_id)).fetchall()
            connection.execute(
                "UPDATE update_candidates SET status = 'CONFLICT', blocked_reason = 'TARGET_SUPERSEDED', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE target_claim_id = ? "
                "AND candidate_id <> ? AND status IN ('PENDING_COMPARISON', 'PENDING_REVIEW', 'APPROVED')",
                (row["target_claim_id"], candidate_id),
            )
            for conflict in conflicting:
                self._audit_candidate_transition(connection, conflict['candidate_id'], conflict['status'])
            patch = json.loads(row["patch_json"])
            delta = len(patch["replacement"]) - (int(patch["end"]) - int(patch["start"]))
            if delta:
                connection.execute(
                    "UPDATE knowledge_claims SET span_start = span_start + ?, span_end = span_end + ?, "
                    "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE note_id = ? AND status = 'ACTIVE' "
                    'AND span_start >= ? AND claim_id <> ?',
                    (delta, delta, row["target_note_id"], patch["end"], successor_id),
                )
            connection.execute(
                "INSERT INTO events(event_type, message, details_json) VALUES "
                "('SEMANTIC_UPDATE_APPLIED', 'Actualización semántica aplicada tras aprobación', ?)",
                (json.dumps({'candidate_id': candidate_id, 'note_id': row['target_note_id'],
                             'proposal_revision': row['proposal_revision'], 'actor': row['reviewed_by'],
                             'review_batch_id': row['review_batch_id'], 'automation_run_id': row['automation_run_id'],
                             'successor_id': successor_id}),),
            )

    def revision_content(self, candidate_id: int) -> str:
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT content_text FROM note_revisions WHERE candidate_id = ? ORDER BY revision DESC LIMIT 1",
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise ValueError("No existe snapshot para recuperar la actualización")
            return row["content_text"]

    def proposal_versions(self, candidate_id: int) -> list[dict]:
        with closing(self.database.connect(readonly=True)) as connection:
            result = []
            for row in connection.execute('SELECT * FROM maintenance_proposal_versions WHERE candidate_id=? '
                                          'ORDER BY revision', (candidate_id,)):
                value = dict(row)
                value['snapshot'] = json.loads(value.pop('snapshot_json'))
                result.append(value)
            return result

    def reject_candidate(self, candidate_id: int, *, expected_revision: int, actor: str, reason: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute('SELECT status,proposal_revision FROM update_candidates WHERE candidate_id=?',
                                     (candidate_id,)).fetchone()
            if row is None or row['proposal_revision'] != expected_revision or row['status'] not in {
                'PENDING_COMPARISON', 'PENDING_REVIEW', 'CONFLICT'
            }:
                raise KnowledgeConflict('La propuesta cambió o ya fue resuelta')
            connection.execute("UPDATE update_candidates SET status='REJECTED',blocked_reason='HUMAN_REJECTED',"
                               "reviewed_by=?,reviewed_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE candidate_id=?",
                               (actor, candidate_id))
            connection.execute('INSERT INTO events(event_type,message,details_json) VALUES (?,?,?)',
                               ('MAINTENANCE_PROPOSAL_REJECTED', 'Propuesta rechazada tras revisión',
                                json.dumps({'candidate_id': candidate_id, 'revision': expected_revision,
                                            'actor': actor, 'reason': reason})))

    def evidence_quote(self, claim_id: int) -> str:
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT quote FROM evidence_links WHERE claim_id = ? ORDER BY evidence_id LIMIT 1", (claim_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Claim sin evidencia local")
            return row["quote"]

    def mark_candidate(self, candidate_id: int, status: str, *, reason: str | None = None,
                       expected_status: str | None = None, expected_revision: int | None = None) -> None:
        if status not in {"REJECTED", "CONFLICT", "ERROR"}:
            raise ValueError("Estado de candidato no permitido")
        with self.database.transaction(immediate=True) as connection:
            prior = connection.execute('SELECT status,blocked_reason FROM update_candidates WHERE candidate_id=?',
                                       (candidate_id,)).fetchone()
            changed = connection.execute(
                "UPDATE update_candidates SET status = ?, blocked_reason = COALESCE(?, blocked_reason), "
                "reviewed_at = COALESCE(reviewed_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE candidate_id = ? "
                "AND status NOT IN ('APPLIED', 'REJECTED') "
                "AND (? IS NULL OR status=?) AND (? IS NULL OR proposal_revision=?)",
                (status, reason, candidate_id, expected_status, expected_status, expected_revision, expected_revision),
            )
            if changed.rowcount and (prior['status'] != status or
                                     (reason is not None and reason != prior['blocked_reason'])):
                self._audit_candidate_transition(connection, candidate_id, prior['status'])
