CREATE TABLE automation_runs (
 run_id TEXT PRIMARY KEY,
 simulation_id TEXT NOT NULL UNIQUE REFERENCES automation_simulations(simulation_id),
 policy_id INTEGER NOT NULL,
 policy_revision INTEGER NOT NULL,
 policy_state_revision INTEGER NOT NULL,
 control_revision INTEGER NOT NULL REFERENCES automation_control_history(revision),
 status TEXT NOT NULL DEFAULT 'READY' CHECK(status IN ('READY','RUNNING','RECOVERY_REQUIRED','COMPLETE')),
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 completed_at TEXT,
 FOREIGN KEY(policy_id,policy_revision) REFERENCES automation_policy_versions(policy_id,revision)
);
CREATE TABLE automation_run_items (
 run_id TEXT NOT NULL REFERENCES automation_runs(run_id),
 candidate_id INTEGER NOT NULL,
 proposal_revision INTEGER NOT NULL,
 position INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','SKIPPED','APPLIED','CONFLICT','FAILED','EXTERNALLY_RESOLVED')),
 result_json TEXT,
 PRIMARY KEY(run_id,candidate_id),
 UNIQUE(run_id,position)
);
CREATE TABLE automation_reservations (
 run_id TEXT NOT NULL,
 candidate_id INTEGER NOT NULL,
 proposal_revision INTEGER NOT NULL,
 policy_id INTEGER NOT NULL REFERENCES automation_policies(policy_id),
 utc_day TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d','now')),
 reserved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 PRIMARY KEY(run_id,candidate_id),
 UNIQUE(candidate_id,proposal_revision),
 FOREIGN KEY(run_id,candidate_id) REFERENCES automation_run_items(run_id,candidate_id)
);
ALTER TABLE update_candidates ADD COLUMN automation_run_id TEXT REFERENCES automation_runs(run_id);
CREATE INDEX automation_runs_status ON automation_runs(status,created_at);
CREATE INDEX automation_reservations_daily ON automation_reservations(policy_id,utc_day);
CREATE TRIGGER automation_run_identity_immutable
 BEFORE UPDATE OF simulation_id,policy_id,policy_revision,policy_state_revision,control_revision ON automation_runs
 BEGIN SELECT RAISE(ABORT,'automation run authorization is immutable'); END;
CREATE TRIGGER automation_run_item_identity_immutable
 BEFORE UPDATE OF run_id,candidate_id,proposal_revision,position ON automation_run_items
 BEGIN SELECT RAISE(ABORT,'automation run item identity is immutable'); END;
CREATE TRIGGER automation_reservations_no_update BEFORE UPDATE ON automation_reservations
 BEGIN SELECT RAISE(ABORT,'automation reservations are immutable'); END;
CREATE TRIGGER automation_reservations_no_delete BEFORE DELETE ON automation_reservations
 BEGIN SELECT RAISE(ABORT,'automation reservations are immutable'); END;
