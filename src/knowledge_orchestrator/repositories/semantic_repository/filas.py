"""Normalización de texto y traducción de filas SQLite al dominio."""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from pathlib import Path

from knowledge_orchestrator.domain.semantic_models import (
    KnowledgeClaim,
    SemanticJob,
    UpdateCandidate,
)


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
