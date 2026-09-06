ALTER TABLE knowledge_claims ADD COLUMN derived_from_claim_id INTEGER REFERENCES knowledge_claims(claim_id);
ALTER TABLE evidence_links ADD COLUMN source_content_hash TEXT;
ALTER TABLE update_candidates ADD COLUMN proposal_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE update_candidates ADD COLUMN reviewed_by TEXT;
ALTER TABLE update_candidates ADD COLUMN applied_successor_id INTEGER REFERENCES knowledge_claims(claim_id);

CREATE TABLE maintenance_proposal_versions (
 candidate_id INTEGER NOT NULL REFERENCES update_candidates(candidate_id),
 revision INTEGER NOT NULL CHECK(revision > 0),
 snapshot_json TEXT NOT NULL,
 actor TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
 PRIMARY KEY(candidate_id, revision)
);
CREATE TRIGGER maintenance_proposal_no_update BEFORE UPDATE ON maintenance_proposal_versions
 BEGIN SELECT RAISE(ABORT, 'proposal versions are immutable'); END;
CREATE TRIGGER maintenance_proposal_no_delete BEFORE DELETE ON maintenance_proposal_versions
 BEGIN SELECT RAISE(ABORT, 'proposal versions are immutable'); END;
CREATE INDEX claims_derived_source ON knowledge_claims(derived_from_claim_id);
