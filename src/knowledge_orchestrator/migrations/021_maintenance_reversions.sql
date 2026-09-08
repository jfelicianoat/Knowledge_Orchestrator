-- Una reversión es otra decisión/publicación, nunca el borrado de una aplicación.
CREATE TABLE maintenance_reversions (
 reversion_id TEXT PRIMARY KEY,
 candidate_id INTEGER NOT NULL REFERENCES update_candidates(candidate_id),
 owner TEXT NOT NULL CHECK(length(trim(owner)) > 0),
 request_key TEXT NOT NULL,
 request_json TEXT NOT NULL,
 plan_json TEXT NOT NULL,
 plan_hash TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'PREVIEW' CHECK(status IN ('PREVIEW','APPLYING','APPLIED','CONFLICT')),
 reason TEXT,
 error_code TEXT,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 confirmed_at TEXT,
 finished_at TEXT,
 UNIQUE(owner, request_key)
);
CREATE UNIQUE INDEX maintenance_reversion_once ON maintenance_reversions(candidate_id)
 WHERE status IN ('APPLYING','APPLIED');
CREATE TRIGGER reversion_plan_immutable BEFORE UPDATE ON maintenance_reversions
 WHEN NEW.reversion_id<>OLD.reversion_id OR NEW.candidate_id<>OLD.candidate_id
 OR NEW.owner<>OLD.owner OR NEW.request_key<>OLD.request_key OR NEW.request_json<>OLD.request_json
 OR NEW.plan_json<>OLD.plan_json OR NEW.plan_hash<>OLD.plan_hash OR NEW.created_at<>OLD.created_at
 OR (OLD.status<>'PREVIEW' AND NEW.reason IS NOT OLD.reason)
 OR (OLD.status<>'PREVIEW' AND NEW.confirmed_at IS NOT OLD.confirmed_at)
 OR (OLD.status='PREVIEW' AND NEW.status NOT IN ('PREVIEW','APPLYING'))
 OR (OLD.status='APPLYING' AND NEW.status NOT IN ('APPLYING','APPLIED','CONFLICT'))
 OR (OLD.status IN ('APPLIED','CONFLICT'))
 BEGIN SELECT RAISE(ABORT, 'reversion plan and decisions are immutable'); END;
CREATE TRIGGER reversion_no_delete BEFORE DELETE ON maintenance_reversions
 BEGIN SELECT RAISE(ABORT, 'reversions are immutable'); END;

CREATE TABLE maintenance_reversion_notes (
 reversion_id TEXT NOT NULL REFERENCES maintenance_reversions(reversion_id),
 note_id INTEGER NOT NULL REFERENCES notes(note_id),
 PRIMARY KEY(reversion_id,note_id)
);
CREATE INDEX reversion_notes_by_note ON maintenance_reversion_notes(note_id,reversion_id);
CREATE TRIGGER reversion_notes_no_update BEFORE UPDATE ON maintenance_reversion_notes
 BEGIN SELECT RAISE(ABORT, 'reversion reservations are immutable'); END;
CREATE TRIGGER reversion_notes_no_delete BEFORE DELETE ON maintenance_reversion_notes
 BEGIN SELECT RAISE(ABORT, 'reversion reservations are immutable'); END;
