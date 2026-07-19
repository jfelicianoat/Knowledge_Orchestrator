from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Volatility = Literal["LOW", "MEDIUM", "HIGH"]
Relation = Literal["UNKNOWN", "SUPPORTS", "EXTENDS", "CONTRADICTS", "SUPERSEDES", "UNRELATED", "UNCERTAIN"]
Impact = Literal["LOW", "MEDIUM", "HIGH"]


@dataclass(frozen=True, slots=True)
class ExtractedClaim:
    statement: str
    claim_type: str
    volatility: Volatility
    span_start: int
    span_end: int
    quote: str
    entities: tuple[str, ...] = ()
    observed_at: str | None = None
    source_date: str | None = None
    manual_lock: bool = False


@dataclass(frozen=True, slots=True)
class KnowledgeClaim:
    claim_id: int
    note_id: int
    source_capture_id: str
    topic_id: int | None
    statement: str
    normalized_statement: str
    claim_type: str
    volatility: Volatility
    observed_at: str | None
    source_date: str | None
    span_start: int
    span_end: int
    entities: tuple[str, ...]
    manual_lock: bool
    status: str


@dataclass(frozen=True, slots=True)
class UpdateCandidate:
    candidate_id: int
    target_note_id: int
    target_claim_id: int
    new_claim_id: int
    relation: Relation
    confidence: float | None
    impact: Impact | None
    status: str
    retrieval_reason: str
    rationale: str | None
    replacement_text: str | None
    patch_json: str | None
    diff_text: str | None
    base_hash: str | None
    result_hash: str | None
    temp_path: Path | None
    blocked_reason: str | None


@dataclass(frozen=True, slots=True)
class ComparisonDecision:
    relation: Literal["SUPPORTS", "EXTENDS", "CONTRADICTS", "SUPERSEDES", "UNRELATED", "UNCERTAIN"]
    confidence: float
    impact: Impact
    rationale: str
    replacement_text: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticJob:
    job_id: str
    kind: str
    note_id: int | None
    candidate_id: int | None
    status: str
    idempotency_key: str
    request_json: str
    broker_task_id: str | None
    status_url: str | None
    attempt: int
    next_retry_at: str | None
