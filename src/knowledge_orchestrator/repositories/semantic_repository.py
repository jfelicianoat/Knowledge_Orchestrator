from __future__ import annotations

import json
import math
import re
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import Iterable

from knowledge_orchestrator.domain.semantic_models import (
    ComparisonDecision,
    ExtractedClaim,
    KnowledgeClaim,
    SemanticJob,
    UpdateCandidate,
)

from .database import Database


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[\w]+", plain, flags=re.UNICODE))


def _claim(row: sqlite3.Row) -> KnowledgeClaim:
    return KnowledgeClaim(
        claim_id=int(row["claim_id"]),
        note_id=int(row["note_id"]),
        source_capture_id=row["source_capture_id"],
        topic_id=int(row["topic_id"]) if row["topic_id"] is not None else None,
        statement=row["statement"],
        normalized_statement=row["normalized_statement"],
        claim_type=row["claim_type"],
        volatility=row["volatility"],
        observed_at=row["observed_at"],
        source_date=row["source_date"],
        span_start=int(row["span_start"]),
        span_end=int(row["span_end"]),
        entities=tuple(json.loads(row["entities_json"])),
        manual_lock=bool(row["manual_lock"]),
        status=row["status"],
    )


def _candidate(row: sqlite3.Row) -> UpdateCandidate:
    return UpdateCandidate(
        candidate_id=int(row["candidate_id"]),
        target_note_id=int(row["target_note_id"]),
        target_claim_id=int(row["target_claim_id"]),
        new_claim_id=int(row["new_claim_id"]),
        relation=row["relation"],
        confidence=float(row["confidence"]) if row["confidence"] is not None else None,
        impact=row["impact"],
        status=row["status"],
        retrieval_reason=row["retrieval_reason"],
        rationale=row["rationale"],
        replacement_text=row["replacement_text"],
        patch_json=row["patch_json"],
        diff_text=row["diff_text"],
        base_hash=row["base_hash"],
        result_hash=row["result_hash"],
        temp_path=Path(row["temp_path"]) if row["temp_path"] else None,
        blocked_reason=row["blocked_reason"],
    )


def _job(row: sqlite3.Row) -> SemanticJob:
    return SemanticJob(
        job_id=row["job_id"], kind=row["kind"], note_id=row["note_id"], candidate_id=row["candidate_id"],
        status=row["status"], idempotency_key=row["idempotency_key"], request_json=row["request_json"],
        broker_task_id=row["broker_task_id"], status_url=row["status_url"], attempt=int(row["attempt"]),
        next_retry_at=row["next_retry_at"],
    )


class SemanticRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def note_context(self, note_id: int) -> sqlite3.Row:
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT n.note_id, n.capture_id, n.topic_id, n.vault_path, n.status, c.metadata_json "
                "FROM notes n JOIN captures c ON c.capture_id = n.capture_id WHERE n.note_id = ?",
                (note_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Nota inexistente")
            return row

    def add_claim(self, note_id: int, claim: ExtractedClaim, *, source_path: Path) -> KnowledgeClaim:
        context = self.note_context(note_id)
        entities = sorted({item.strip() for item in claim.entities if item.strip()}, key=str.casefold)
        normalized = normalize_text(claim.statement)
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO knowledge_claims(note_id, source_capture_id, topic_id, statement, normalized_statement, "
                "claim_type, volatility, observed_at, source_date, span_start, span_end, entities_json, manual_lock) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(note_id, span_start, span_end, normalized_statement) DO NOTHING",
                (
                    note_id, context["capture_id"], context["topic_id"], claim.statement.strip(), normalized,
                    claim.claim_type.strip(), claim.volatility, claim.observed_at, claim.source_date,
                    claim.span_start, claim.span_end, json.dumps(entities, ensure_ascii=False), int(claim.manual_lock),
                ),
            )
            row = connection.execute(
                "SELECT * FROM knowledge_claims WHERE note_id = ? AND span_start = ? AND span_end = ? "
                "AND normalized_statement = ?",
                (note_id, claim.span_start, claim.span_end, normalized),
            ).fetchone()
            connection.execute(
                "INSERT INTO evidence_links(claim_id, source_capture_id, source_note_id, quote, span_start, span_end, source_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                (
                    row["claim_id"], context["capture_id"], note_id, claim.quote,
                    claim.span_start, claim.span_end, str(source_path),
                ),
            )
            return _claim(row)

    def get_claim(self, claim_id: int) -> KnowledgeClaim | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute("SELECT * FROM knowledge_claims WHERE claim_id = ?", (claim_id,)).fetchone()
            return _claim(row) if row else None

    def list_claims(self, note_id: int | None = None, *, status: str | None = None) -> list[KnowledgeClaim]:
        clauses: list[str] = []
        parameters: list[object] = []
        if note_id is not None:
            clauses.append("note_id = ?")
            parameters.append(note_id)
        if status is not None:
            clauses.append("status = ?")
            parameters.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with closing(self.database.connect()) as connection:
            rows = connection.execute("SELECT * FROM knowledge_claims" + where + " ORDER BY claim_id", parameters).fetchall()
            return [_claim(row) for row in rows]

    def set_manual_lock(self, claim_id: int, locked: bool) -> None:
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE knowledge_claims SET manual_lock = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE claim_id = ? AND status = 'ACTIVE'",
                (int(locked), claim_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Claim activo inexistente")

    def find_related(self, new_claim: KnowledgeClaim, *, limit: int = 20) -> list[tuple[KnowledgeClaim, str]]:
        entity_keys = {normalize_text(item) for item in new_claim.entities if normalize_text(item)}
        tokens = list(entity_keys) or [token for token in new_claim.normalized_statement.split() if len(token) >= 4]
        tokens = tokens[:12]
        fts_ids: set[int] = set()
        if tokens:
            expression = " OR ".join(f'"{token}"' for token in tokens)
            with closing(self.database.connect()) as connection:
                rows = connection.execute(
                    "SELECT rowid FROM knowledge_claims_fts WHERE knowledge_claims_fts MATCH ? LIMIT ?",
                    (expression, limit * 4),
                ).fetchall()
                fts_ids = {int(row[0]) for row in rows}

        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT k.* FROM knowledge_claims k JOIN notes n ON n.note_id = k.note_id "
                "WHERE k.status = 'ACTIVE' AND n.status = 'PUBLISHED' AND k.note_id <> ? "
                "AND (? IS NULL OR k.topic_id = ?) ORDER BY k.claim_id DESC LIMIT ?",
                (new_claim.note_id, new_claim.topic_id, new_claim.topic_id, limit * 10),
            ).fetchall()
        matches: list[tuple[KnowledgeClaim, str]] = []
        for row in rows:
            existing = _claim(row)
            overlap = entity_keys.intersection(normalize_text(item) for item in existing.entities)
            if overlap:
                reason = "entities:" + ",".join(sorted(overlap))
            elif existing.claim_id in fts_ids:
                reason = "fts5"
            else:
                continue
            matches.append((existing, reason))
            if len(matches) >= limit:
                break
        return matches

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
                "INSERT INTO update_candidates(target_note_id, target_claim_id, new_claim_id, retrieval_reason, blocked_reason) "
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
            row = connection.execute("SELECT * FROM update_candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
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
            status = "PENDING_REVIEW" if decision.relation in {"EXTENDS", "CONTRADICTS", "SUPERSEDES"} and not blocked else "REJECTED"
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

    def create_job(
        self,
        *,
        job_id: str,
        kind: str,
        idempotency_key: str,
        request: dict,
        note_id: int | None = None,
        candidate_id: int | None = None,
    ) -> SemanticJob:
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO semantic_jobs(job_id, kind, note_id, candidate_id, idempotency_key, request_json) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(job_id) DO NOTHING",
                (job_id, kind, note_id, candidate_id, idempotency_key, json.dumps(request, ensure_ascii=False)),
            )
            return _job(connection.execute("SELECT * FROM semantic_jobs WHERE job_id = ?", (job_id,)).fetchone())

    def list_dispatchable_jobs(self) -> list[SemanticJob]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM semantic_jobs WHERE status = 'READY' AND "
                "(next_retry_at IS NULL OR next_retry_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) "
                "ORDER BY created_at, job_id"
            ).fetchall()
            return [_job(row) for row in rows]

    def get_job(self, job_id: str) -> SemanticJob | None:
        with closing(self.database.connect()) as connection:
            row = connection.execute("SELECT * FROM semantic_jobs WHERE job_id = ?", (job_id,)).fetchone()
            return _job(row) if row else None

    def claim_job(self, job_id: str) -> SemanticJob | None:
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE semantic_jobs SET status = 'SUBMITTING', attempt = attempt + 1, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE job_id = ? AND status = 'READY'",
                (job_id,),
            )
            if cursor.rowcount != 1:
                return None
            return _job(connection.execute("SELECT * FROM semantic_jobs WHERE job_id = ?", (job_id,)).fetchone())

    def accept_job(self, job_id: str, response: dict) -> None:
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE semantic_jobs SET status = 'QUEUED', broker_task_id = ?, status_url = ?, next_retry_at = NULL, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE job_id = ? AND status = 'SUBMITTING'",
                (response["task_id"], response["status_url"], job_id),
            )

    def retry_job(self, job_id: str, *, next_retry_at: str, message: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE semantic_jobs SET status = 'READY', next_retry_at = ?, error_code = 'BROKER_UNAVAILABLE', "
                "error_message = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE job_id = ? AND status = 'SUBMITTING'",
                (next_retry_at, message, job_id),
            )

    def fail_job(self, job_id: str, code: str, message: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE semantic_jobs SET status = 'ERROR', error_code = ?, error_message = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE job_id = ? "
                "AND status NOT IN ('SUCCESS', 'ERROR')",
                (code, message, job_id),
            )

    def list_active_jobs(self) -> list[SemanticJob]:
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM semantic_jobs WHERE status IN ('QUEUED', 'PROCESSING') ORDER BY created_at"
            ).fetchall()
            return [_job(row) for row in rows]

    def update_job_status(self, job_id: str, payload: dict) -> tuple[SemanticJob, str | None] | None:
        broker_status = payload["status"]
        if broker_status in {"queued"}:
            target = "QUEUED"
        elif broker_status in {
            "routing", "planning", "resource_planning", "generating", "proposing", "evaluating",
            "debating", "synthesizing", "verifying", "processing",
        }:
            target = "PROCESSING"
        elif broker_status in {"completed", "success"}:
            target = "SUCCESS"
        elif broker_status in {"failed", "error", "cancelled"}:
            target = "ERROR"
        else:
            raise ValueError(f"Estado Broker desconocido: {broker_status}")
        with self.database.transaction(immediate=True) as connection:
            current = connection.execute("SELECT * FROM semantic_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if current is None or current["status"] in {"SUCCESS", "ERROR"}:
                return None
            result_text = None
            error = payload.get("error") or {}
            if target == "SUCCESS":
                result = payload.get("result") or {}
                result_text = result.get("result_markdown") or result.get("assistant_content")
                if not isinstance(result_text, str) or not result_text.strip():
                    raise ValueError("Resultado semántico vacío")
            connection.execute(
                "UPDATE semantic_jobs SET status = ?, result_json = ?, error_code = ?, error_message = ?, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE job_id = ?",
                (
                    "PROCESSING" if target == "SUCCESS" else target,
                    json.dumps(payload.get("result"), ensure_ascii=False) if target == "SUCCESS" else None,
                    error.get("code") if target == "ERROR" else None,
                    error.get("message") if target == "ERROR" else None,
                    job_id,
                ),
            )
            return _job(connection.execute("SELECT * FROM semantic_jobs WHERE job_id = ?", (job_id,)).fetchone()), result_text

    def complete_job(self, job_id: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE semantic_jobs SET status = 'SUCCESS', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                "WHERE job_id = ? AND status = 'PROCESSING' AND result_json IS NOT NULL",
                (job_id,),
            )

    def recover_jobs(self) -> None:
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE semantic_jobs SET status = 'READY', next_retry_at = NULL, "
                "updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE status = 'SUBMITTING'"
            )

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

    def record_embedding(self, claim_id: int, model: str, vector: Iterable[float]) -> None:
        values = [float(value) for value in vector]
        if not values or any(not math.isfinite(value) for value in values):
            raise ValueError("Embedding inválido")
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO claim_embeddings(claim_id, model, dimensions, vector_json) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(claim_id) DO UPDATE SET model = excluded.model, dimensions = excluded.dimensions, "
                "vector_json = excluded.vector_json, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                (claim_id, model, len(values), json.dumps(values)),
            )

    def nearest_embeddings(self, claim_id: int, *, limit: int = 10, minimum_similarity: float = 0.75) -> list[int]:
        with closing(self.database.connect()) as connection:
            source = connection.execute(
                "SELECT model, dimensions, vector_json FROM claim_embeddings WHERE claim_id = ?", (claim_id,)
            ).fetchone()
            if source is None:
                return []
            rows = connection.execute(
                "SELECT e.claim_id, e.vector_json FROM claim_embeddings e "
                "JOIN knowledge_claims k ON k.claim_id = e.claim_id "
                "JOIN notes n ON n.note_id = k.note_id "
                "WHERE e.claim_id <> ? AND e.model = ? AND e.dimensions = ? AND k.status = 'ACTIVE' "
                "AND n.status = 'PUBLISHED'",
                (claim_id, source["model"], source["dimensions"]),
            ).fetchall()
        origin = json.loads(source["vector_json"])
        norm_origin = math.sqrt(sum(value * value for value in origin))
        scored: list[tuple[float, int]] = []
        for row in rows:
            vector = json.loads(row["vector_json"])
            norm = math.sqrt(sum(value * value for value in vector))
            similarity = sum(a * b for a, b in zip(origin, vector)) / (norm_origin * norm) if norm_origin and norm else 0.0
            if similarity >= minimum_similarity:
                scored.append((similarity, int(row["claim_id"])))
        return [claim for _, claim in sorted(scored, reverse=True)[:limit]]
