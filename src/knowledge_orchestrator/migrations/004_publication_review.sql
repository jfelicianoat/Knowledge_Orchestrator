ALTER TABLE captures ADD COLUMN archive_path TEXT;
ALTER TABLE captures ADD COLUMN rejected_source_path TEXT;

ALTER TABLE notes ADD COLUMN workflow_id TEXT REFERENCES workflows(workflow_id) ON DELETE RESTRICT;
ALTER TABLE notes ADD COLUMN topic_id INTEGER REFERENCES topics(topic_id) ON DELETE SET NULL;
ALTER TABLE notes ADD COLUMN profile_id INTEGER REFERENCES profiles(profile_id) ON DELETE SET NULL;
ALTER TABLE notes ADD COLUMN temp_path TEXT;
ALTER TABLE notes ADD COLUMN content_hash TEXT;
ALTER TABLE notes ADD COLUMN rejected_path TEXT;
ALTER TABLE notes ADD COLUMN source_archive_path TEXT;
ALTER TABLE notes ADD COLUMN published_at TEXT;
ALTER TABLE notes ADD COLUMN rejected_at TEXT;

CREATE UNIQUE INDEX idx_notes_workflow ON notes(workflow_id) WHERE workflow_id IS NOT NULL;
CREATE INDEX idx_notes_status ON notes(status, updated_at);

CREATE TABLE reprocess_intents (
    intent_id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id TEXT NOT NULL REFERENCES captures(capture_id) ON DELETE RESTRICT,
    source_note_id INTEGER NOT NULL REFERENCES notes(note_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK (revision > 1),
    source_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PREPARED', 'COPIED', 'PLANNED', 'ERROR')),
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(capture_id, revision)
);

CREATE INDEX idx_reprocess_status ON reprocess_intents(status, created_at);
