CREATE TABLE automation_schedules (
 policy_id INTEGER PRIMARY KEY REFERENCES automation_policies(policy_id),
 next_check_at REAL NOT NULL DEFAULT 0,
 lease_token TEXT,
 lease_until REAL,
 last_checked_at REAL,
 last_fingerprint TEXT,
 last_simulation_id TEXT REFERENCES automation_simulations(simulation_id),
 last_run_id TEXT REFERENCES automation_runs(run_id),
 candidate_cursor INTEGER NOT NULL DEFAULT 0,
 failures INTEGER NOT NULL DEFAULT 0,
 error_code TEXT
);
CREATE INDEX automation_schedules_due ON automation_schedules(next_check_at,policy_id);
CREATE TABLE automation_schedule_plans (
 policy_id INTEGER NOT NULL REFERENCES automation_policies(policy_id),
 fingerprint TEXT NOT NULL,
 simulation_id TEXT NOT NULL REFERENCES automation_simulations(simulation_id),
 run_id TEXT REFERENCES automation_runs(run_id),
 PRIMARY KEY(policy_id,fingerprint)
);
