"""Afirmaciones extraídas de una nota, y cómo se buscan las relacionadas.

La búsqueda de relacionadas es léxica y deliberadamente simple: el paso
semántico caro va aparte, con embeddings, y solo sobre lo que este filtro
deja pasar.
"""
from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

from knowledge_orchestrator.domain.semantic_models import (
    ExtractedClaim,
    KnowledgeClaim,
)
from knowledge_orchestrator.repositories.semantic_repository.base import RepositorioBase
from knowledge_orchestrator.repositories.semantic_repository.filas import _claim, normalize_text


class AfirmacionesMixin(RepositorioBase):
    """Alta, consulta y bloqueo manual de afirmaciones."""

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
                "INSERT INTO evidence_links(claim_id, source_capture_id, source_note_id, quote, "
                "span_start, span_end, source_path) "
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
            rows = connection.execute(
                "SELECT * FROM knowledge_claims" + where + " ORDER BY claim_id", parameters
            ).fetchall()
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
