CREATE TABLE knowledge_queries (
    query_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    knowledge_state TEXT NOT NULL CHECK (knowledge_state IN ('current', 'historical', 'all')),
    status TEXT NOT NULL CHECK (status IN ('READY', 'SUBMITTING', 'QUEUED', 'PROCESSING', 'SUCCESS', 'ERROR', 'STALE')),
    request_json TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    result_json TEXT,
    broker_task_id TEXT,
    status_url TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(owner, key_hash)
);
CREATE INDEX idx_knowledge_query_queue ON knowledge_queries(status, next_retry_at, created_at);

CREATE TABLE api_ingestions (
    ingestion_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    capture_id TEXT NOT NULL UNIQUE,
    markdown_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'DELIVERED', 'CONFLICT')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(owner, key_hash)
);
