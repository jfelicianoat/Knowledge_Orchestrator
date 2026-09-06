CREATE TABLE monitored_sources (
 source_id INTEGER PRIMARY KEY,
 config_json TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
 owner TEXT NOT NULL,
 create_key TEXT NOT NULL,
 create_payload TEXT NOT NULL,
 next_check_at REAL NOT NULL DEFAULT 0,
 last_checked_at REAL,
 last_changed_at REAL,
 last_known_hash TEXT,
 etag TEXT,
 last_modified TEXT,
 failures INTEGER NOT NULL DEFAULT 0,
 last_error_code TEXT,
 lease_until REAL,
 check_id TEXT,
 UNIQUE(owner, create_key)
);
CREATE TABLE source_revisions (
 source_id INTEGER NOT NULL REFERENCES monitored_sources(source_id),
 revision INTEGER NOT NULL,
 config_json TEXT NOT NULL,
 actor TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
 PRIMARY KEY(source_id, revision)
);
CREATE TRIGGER source_revisions_no_update BEFORE UPDATE ON source_revisions
 BEGIN SELECT RAISE(ABORT, 'source revisions are immutable'); END;
CREATE TRIGGER source_revisions_no_delete BEFORE DELETE ON source_revisions
 BEGIN SELECT RAISE(ABORT, 'source revisions are immutable'); END;
CREATE TABLE source_checks (
 check_id TEXT PRIMARY KEY,
 source_id INTEGER NOT NULL REFERENCES monitored_sources(source_id),
 source_revision INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('RUNNING','CHANGED','UNCHANGED','ERROR','ABANDONED','SUPERSEDED')),
 started_at REAL NOT NULL,
 finished_at REAL,
 error_code TEXT
);
CREATE TABLE source_changes (
 change_id TEXT PRIMARY KEY,
 check_id TEXT NOT NULL REFERENCES source_checks(check_id),
 source_id INTEGER NOT NULL REFERENCES monitored_sources(source_id),
 source_revision INTEGER NOT NULL,
 item_key TEXT NOT NULL,
 previous_hash TEXT,
 content_hash TEXT NOT NULL,
 title TEXT NOT NULL,
 content TEXT NOT NULL,
 source_url TEXT NOT NULL,
 provenance_json TEXT NOT NULL,
 observed_at REAL NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('REVIEW','READY','DELIVERED')),
 ingestion_id TEXT REFERENCES api_ingestions(ingestion_id),
 delivery_failures INTEGER NOT NULL DEFAULT 0,
 delivery_error TEXT,
 next_delivery_at REAL NOT NULL DEFAULT 0,
 UNIQUE(check_id, item_key)
);
CREATE TABLE source_items (
 source_id INTEGER NOT NULL REFERENCES monitored_sources(source_id),
 item_key TEXT NOT NULL,
 content_hash TEXT NOT NULL,
 last_change_id TEXT NOT NULL REFERENCES source_changes(change_id),
 PRIMARY KEY(source_id, item_key)
);
CREATE TABLE source_commands (
 owner TEXT NOT NULL,
 command_key TEXT NOT NULL,
 payload TEXT NOT NULL,
 PRIMARY KEY(owner, command_key)
);
CREATE INDEX source_checks_source ON source_checks(source_id, started_at);
CREATE INDEX source_changes_status ON source_changes(status, observed_at);
