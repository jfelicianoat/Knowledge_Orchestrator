CREATE TABLE review_batches (
 batch_id TEXT PRIMARY KEY,
 owner TEXT NOT NULL,
 create_key TEXT NOT NULL,
 request_json TEXT NOT NULL,
 plan_json TEXT NOT NULL,
 plan_hash TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','READY','RUNNING','RECOVERY_REQUIRED','COMPLETE')),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 confirmed_at TEXT,
 completed_at TEXT,
 UNIQUE(owner,create_key)
);
CREATE TABLE review_batch_items (
 batch_id TEXT NOT NULL REFERENCES review_batches(batch_id),
 position INTEGER NOT NULL,
 candidate_id INTEGER NOT NULL,
 expected_revision INTEGER NOT NULL CHECK(expected_revision>=0),
 status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','SKIPPED','APPLIED','CONFLICT','FAILED','EXTERNALLY_RESOLVED')),
 result_json TEXT,
 PRIMARY KEY(batch_id,candidate_id),
 UNIQUE(batch_id,position)
);
ALTER TABLE update_candidates ADD COLUMN review_batch_id TEXT REFERENCES review_batches(batch_id);
CREATE TRIGGER review_batch_plan_immutable BEFORE UPDATE OF owner,create_key,request_json,plan_json,plan_hash
 ON review_batches BEGIN SELECT RAISE(ABORT,'review batch plans are immutable'); END;
CREATE TRIGGER review_batch_item_identity_immutable BEFORE UPDATE OF batch_id,position,candidate_id,expected_revision
 ON review_batch_items BEGIN SELECT RAISE(ABORT,'review batch item identities are immutable'); END;
CREATE INDEX review_batches_status ON review_batches(status,created_at);
