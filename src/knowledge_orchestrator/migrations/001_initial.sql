CREATE TABLE captures (
    capture_id TEXT PRIMARY KEY,
    contract_version TEXT NOT NULL,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'STAGED', 'PENDING', 'SUBMITTING', 'QUEUED', 'PROCESSING',
        'COMPLETED', 'FAILED', 'REJECTED', 'CANCELLED'
    )),
    source_path TEXT,
    staging_path TEXT,
    processing_path TEXT,
    sha256 TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    transcript_content TEXT NOT NULL,
    last_error_code TEXT,
    last_error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_captures_status ON captures(status);
CREATE INDEX idx_captures_sha256 ON captures(sha256);

CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    capture_id TEXT NOT NULL REFERENCES captures(capture_id) ON DELETE CASCADE,
    workflow_id TEXT,
    step_id TEXT,
    status TEXT NOT NULL,
    request_json TEXT,
    response_json TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT REFERENCES captures(capture_id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_events_capture_id ON events(capture_id);

CREATE TABLE notes (
    note_id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL REFERENCES captures(capture_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL DEFAULT 1,
    vault_path TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(capture_id, revision)
);

CREATE TABLE profiles (
    profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE topics (
    topic_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    position INTEGER NOT NULL,
    folder TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    default_profile_id INTEGER REFERENCES profiles(profile_id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE UNIQUE INDEX idx_topics_position ON topics(position);
