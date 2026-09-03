"""Candidatos de actualización: propuesta, comparación y aplicación.

`prepare_application` y `mark_applied` son la parte que toca ficheros del
vault: se hacen contra un temporal y con hash esperado, para que un fallo a
mitad no deje una nota a medias.
"""
from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

from knowledge_orchestrator.domain.semantic_models import (
    ComparisonDecision,
    KnowledgeClaim,
    UpdateCandidate,
)
from knowledge_orchestrator.repositories.semantic_repository.afirmaciones import AfirmacionesMixin
from knowledge_orchestrator.repositories.semantic_repository.filas import _candidate


class CandidatosMixin(AfirmacionesMixin):
    """Ciclo de vida de un candidato de actualización."""

    def create_candidate(
        self,
        target: KnowledgeClaim,
        new_claim: KnowledgeClaim,
        *,
        retrieval_reason: str,
    ) -> UpdateCandidate:
        blocked = "MANUAL_LOCK" if target.manual_lock else None
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO update_candidates(target_note_id, target_claim_id, new_claim_id, "
                "retrieval_reason, blocked_reason) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(target_claim_id, new_claim_id) DO NOTHING",
                (target.note_id, target.claim_id, new_claim.claim_id, retrieval_reason, blocked),
            )
            row = connection.execute(
                "SELECT * FROM update_candidates WHERE target_claim_id = ? AND new_claim_id = ?",
                (target.claim_id, new_claim.claim_id),
            ).fetchone()
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
    ) -> UpdateCandidate:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT c.*, k.manual_lock, k.status AS claim_status FROM update_candidates c "
                "JOIN knowledge_claims k ON k.claim_id = c.target_claim_id WHERE c.candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            if row is None or row["status"] != "PENDING_COMPARISON":
                raise ValueError("El candidato no está pendiente de comparación")
            if row["claim_status"] != "ACTIVE":
                raise ValueError("El claim objetivo ya no está activo")
            blocked = "MANUAL_LOCK" if bool(row["manual_lock"]) else row["blocked_reason"]
            reviewable = decision.relation in {"EXTENDS", "CONTRADICTS", "SUPERSEDES"} and not blocked
            status = "PENDING_REVIEW" if reviewable else "REJECTED"
            connection.execute(
                "UPDATE update_candidates SET relation = ?, confidence = ?, impact = ?, rationale = ?, "
                "replacement_text = ?, patch_json = ?, diff_text = ?, blocked_reason = ?, status = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE candidate_id = ?",
                (
                    decision.relation, decision.confidence, decision.impact, decision.rationale,
                    decision.replacement_text, patch_json, diff_text, blocked, status, candidate_id,
                ),
            )
            return _candidate(connection.execute(
                "SELECT * FROM update_candidates WHERE candidate_id = ?", (candidate_id,)
            ).fetchone())

    def prepare_application(
        self,
        candidate_id: int,
        *,
        current_content: str,
        base_hash: str,
        result_hash: str,
        temp_path: Path,
        patch_json: str,
    ) -> UpdateCandidate:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT c.*, k.manual_lock, k.status AS claim_status FROM update_candidates c "
                "JOIN knowledge_claims k ON k.claim_id = c.target_claim_id WHERE c.candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            if row is None or row["status"] not in {"PENDING_REVIEW", "APPROVED", "APPLYING"}:
                raise ValueError("El candidato no se puede aprobar")
            if row["claim_status"] != "ACTIVE":
                raise ValueError("El claim objetivo ya no está activo")
            if bool(row["manual_lock"]) or row["blocked_reason"]:
                raise ValueError("El claim objetivo está bloqueado manualmente")
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
                "patch_json = ?, reviewed_at = COALESCE(reviewed_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE candidate_id = ?",
                (base_hash, result_hash, str(temp_path), patch_json, candidate_id),
            )
            return _candidate(connection.execute(
                "SELECT * FROM update_candidates WHERE candidate_id = ?", (candidate_id,)
            ).fetchone())

    def mark_applied(self, candidate_id: int) -> None:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT target_claim_id, target_note_id, patch_json FROM update_candidates "
                "WHERE candidate_id = ? AND status = 'APPLYING'",
                (candidate_id,),
            ).fetchone()
            if row is None:
                return
            connection.execute(
                "UPDATE update_candidates SET status = 'APPLIED', temp_path = NULL, applied_at = "
                "strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE candidate_id = ?",
                (candidate_id,),
            )
            connection.execute(
                "UPDATE knowledge_claims SET status = 'SUPERSEDED', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE claim_id = ?",
                (row["target_claim_id"],),
            )
            connection.execute(
                "UPDATE notes SET content_hash = (SELECT result_hash FROM update_candidates WHERE candidate_id = ?), "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE note_id = ?",
                (candidate_id, row["target_note_id"]),
            )
            connection.execute(
                "UPDATE update_candidates SET status = 'CONFLICT', blocked_reason = 'TARGET_SUPERSEDED', "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE target_claim_id = ? "
                "AND candidate_id <> ? AND status IN ('PENDING_COMPARISON', 'PENDING_REVIEW', 'APPROVED')",
                (row["target_claim_id"], candidate_id),
            )
            patch = json.loads(row["patch_json"])
            delta = len(patch["replacement"]) - (int(patch["end"]) - int(patch["start"]))
            if delta:
                connection.execute(
                    "UPDATE knowledge_claims SET span_start = span_start + ?, span_end = span_end + ?, "
                    "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE note_id = ? AND status = 'ACTIVE' "
                    "AND span_start >= ?",
                    (delta, delta, row["target_note_id"], patch["end"]),
                )
            connection.execute(
                "INSERT INTO events(event_type, message, details_json) VALUES "
                "('SEMANTIC_UPDATE_APPLIED', 'Actualización semántica aplicada tras aprobación', ?)",
                (json.dumps({"candidate_id": candidate_id, "note_id": row["target_note_id"]}),),
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

    def evidence_quote(self, claim_id: int) -> str:
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT quote FROM evidence_links WHERE claim_id = ? ORDER BY evidence_id LIMIT 1", (claim_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Claim sin evidencia local")
            return row["quote"]

    def mark_candidate(self, candidate_id: int, status: str, *, reason: str | None = None) -> None:
        if status not in {"REJECTED", "CONFLICT", "ERROR"}:
            raise ValueError("Estado de candidato no permitido")
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE update_candidates SET status = ?, blocked_reason = COALESCE(?, blocked_reason), "
                "reviewed_at = COALESCE(reviewed_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE candidate_id = ? "
                "AND status NOT IN ('APPLIED', 'REJECTED')",
                (status, reason, candidate_id),
            )
