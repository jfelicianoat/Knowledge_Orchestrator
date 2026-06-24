CREATE TABLE knowledge_claims (
    claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id INTEGER NOT NULL REFERENCES notes(note_id) ON DELETE CASCADE,
    source_capture_id TEXT NOT NULL REFERENCES captures(capture_id) ON DELETE RESTRICT,
    topic_id INTEGER REFERENCES topics(topic_id) ON DELETE SET NULL,
    statement TEXT NOT NULL,
    normalized_statement TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    volatility TEXT NOT NULL CHECK (volatility IN ('LOW', 'MEDIUM', 'HIGH')),
    observed_at TEXT,
    source_date TEXT,
    span_start INTEGER NOT NULL CHECK (span_start >= 0),
    span_end INTEGER NOT NULL CHECK (span_end > span_start),
    entities_json TEXT NOT NULL DEFAULT '[]',
    manual_lock INTEGER NOT NULL DEFAULT 0 CHECK (manual_lock IN (0, 1)),
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'SUPERSEDED', 'RETRACTED')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(note_id, span_start, span_end, normalized_statement)
);

CREATE INDEX idx_claims_note ON knowledge_claims(note_id, status);
CREATE INDEX idx_claims_topic ON knowledge_claims(topic_id, status);
CREATE INDEX idx_claims_source ON knowledge_claims(source_capture_id);

CREATE VIRTUAL TABLE knowledge_claims_fts USING fts5(
    statement,
    entities,
    content='knowledge_claims',
    content_rowid='claim_id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER knowledge_claims_ai AFTER INSERT ON knowledge_claims BEGIN
    INSERT INTO knowledge_claims_fts(rowid, statement, entities)
    VALUES (new.claim_id, new.statement, new.entities_json);
END;

CREATE TRIGGER knowledge_claims_ad AFTER DELETE ON knowledge_claims BEGIN
    INSERT INTO knowledge_claims_fts(knowledge_claims_fts, rowid, statement, entities)
    VALUES ('delete', old.claim_id, old.statement, old.entities_json);
END;

CREATE TRIGGER knowledge_claims_au AFTER UPDATE OF statement, entities_json ON knowledge_claims BEGIN
    INSERT INTO knowledge_claims_fts(knowledge_claims_fts, rowid, statement, entities)
    VALUES ('delete', old.claim_id, old.statement, old.entities_json);
    INSERT INTO knowledge_claims_fts(rowid, statement, entities)
    VALUES (new.claim_id, new.statement, new.entities_json);
END;

CREATE TABLE evidence_links (
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id INTEGER NOT NULL REFERENCES knowledge_claims(claim_id) ON DELETE CASCADE,
    source_capture_id TEXT NOT NULL REFERENCES captures(capture_id) ON DELETE RESTRICT,
    source_note_id INTEGER REFERENCES notes(note_id) ON DELETE SET NULL,
    quote TEXT NOT NULL,
    span_start INTEGER NOT NULL CHECK (span_start >= 0),
    span_end INTEGER NOT NULL CHECK (span_end > span_start),
    source_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(claim_id, source_capture_id, span_start, span_end)
);

CREATE INDEX idx_evidence_claim ON evidence_links(claim_id);
CREATE INDEX idx_evidence_source ON evidence_links(source_capture_id);

CREATE TABLE claim_embeddings (
    claim_id INTEGER PRIMARY KEY REFERENCES knowledge_claims(claim_id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE update_candidates (
    candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_note_id INTEGER NOT NULL REFERENCES notes(note_id) ON DELETE CASCADE,
    target_claim_id INTEGER NOT NULL REFERENCES knowledge_claims(claim_id) ON DELETE RESTRICT,
    new_claim_id INTEGER NOT NULL REFERENCES knowledge_claims(claim_id) ON DELETE RESTRICT,
    relation TEXT NOT NULL DEFAULT 'UNKNOWN'
        CHECK (relation IN ('UNKNOWN', 'SUPPORTS', 'EXTENDS', 'CONTRADICTS', 'SUPERSEDES', 'UNRELATED', 'UNCERTAIN')),
    confidence REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    impact TEXT CHECK (impact IS NULL OR impact IN ('LOW', 'MEDIUM', 'HIGH')),
    status TEXT NOT NULL DEFAULT 'PENDING_COMPARISON'
        CHECK (status IN ('PENDING_COMPARISON', 'PENDING_REVIEW', 'APPROVED', 'APPLYING', 'APPLIED', 'REJECTED', 'CONFLICT', 'ERROR')),
    retrieval_reason TEXT NOT NULL,
    rationale TEXT,
    replacement_text TEXT,
    patch_json TEXT,
    diff_text TEXT,
    base_hash TEXT,
    result_hash TEXT,
    temp_path TEXT,
    blocked_reason TEXT,
    reviewed_at TEXT,
    applied_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(target_claim_id, new_claim_id)
);

CREATE INDEX idx_candidates_status ON update_candidates(status, created_at);
CREATE INDEX idx_candidates_note ON update_candidates(target_note_id, status);

CREATE TABLE note_revisions (
    note_revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id INTEGER NOT NULL REFERENCES notes(note_id) ON DELETE CASCADE,
    candidate_id INTEGER REFERENCES update_candidates(candidate_id) ON DELETE SET NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    content_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(note_id, revision)
);

CREATE INDEX idx_note_revisions_note ON note_revisions(note_id, revision DESC);

CREATE TABLE semantic_jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('EXTRACT', 'COMPARE')),
    note_id INTEGER REFERENCES notes(note_id) ON DELETE CASCADE,
    candidate_id INTEGER REFERENCES update_candidates(candidate_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'READY'
        CHECK (status IN ('READY', 'SUBMITTING', 'QUEUED', 'PROCESSING', 'SUCCESS', 'ERROR')),
    idempotency_key TEXT NOT NULL UNIQUE,
    request_json TEXT NOT NULL,
    broker_task_id TEXT,
    status_url TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    result_json TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK ((kind = 'EXTRACT' AND note_id IS NOT NULL AND candidate_id IS NULL) OR
           (kind = 'COMPARE' AND candidate_id IS NOT NULL))
);

CREATE INDEX idx_semantic_jobs_dispatch ON semantic_jobs(status, next_retry_at, created_at);
