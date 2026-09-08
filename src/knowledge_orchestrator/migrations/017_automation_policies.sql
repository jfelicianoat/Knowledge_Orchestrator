CREATE TABLE automation_policies (
 policy_id INTEGER PRIMARY KEY,
 revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>0),
 state_revision INTEGER NOT NULL DEFAULT 1 CHECK(state_revision>0),
 config_json TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
 approved_by TEXT,
 approved_at TEXT,
 created_by TEXT NOT NULL,
 create_key TEXT NOT NULL,
 create_payload TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 UNIQUE(created_by,create_key)
);
CREATE TABLE automation_policy_versions (
 policy_id INTEGER NOT NULL REFERENCES automation_policies(policy_id),
 revision INTEGER NOT NULL,
 config_json TEXT NOT NULL,
 actor TEXT NOT NULL,
 reason TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 PRIMARY KEY(policy_id,revision)
);
CREATE TABLE automation_policy_decisions (
 policy_id INTEGER NOT NULL,
 revision INTEGER NOT NULL,
 state_revision INTEGER NOT NULL,
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
 actor TEXT NOT NULL,
 reason TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 PRIMARY KEY(policy_id,state_revision),
 FOREIGN KEY(policy_id,revision) REFERENCES automation_policy_versions(policy_id,revision)
);
CREATE TABLE automation_control (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 revision INTEGER NOT NULL DEFAULT 1,
 paused INTEGER NOT NULL DEFAULT 1 CHECK(paused IN (0,1))
);
CREATE TABLE automation_control_history (
 revision INTEGER PRIMARY KEY,
 paused INTEGER NOT NULL CHECK(paused IN (0,1)),
 actor TEXT NOT NULL,
 reason TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT INTO automation_control(singleton) VALUES(1);
INSERT INTO automation_control_history(revision,paused,actor,reason)
 VALUES(1,1,'system:default','Automatización pausada hasta decisión humana explícita');
CREATE TABLE automation_simulations (
 simulation_id TEXT PRIMARY KEY,
 policy_id INTEGER NOT NULL,
 policy_revision INTEGER NOT NULL,
 policy_state_revision INTEGER NOT NULL,
 control_revision INTEGER NOT NULL REFERENCES automation_control_history(revision),
 plan_json TEXT NOT NULL,
 actor TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 FOREIGN KEY(policy_id,policy_revision) REFERENCES automation_policy_versions(policy_id,revision)
);
CREATE TRIGGER automation_policy_versions_no_update BEFORE UPDATE ON automation_policy_versions
 BEGIN SELECT RAISE(ABORT,'policy versions are immutable'); END;
CREATE TRIGGER automation_policy_versions_no_delete BEFORE DELETE ON automation_policy_versions
 BEGIN SELECT RAISE(ABORT,'policy versions are immutable'); END;
CREATE TRIGGER automation_policy_decisions_no_update BEFORE UPDATE ON automation_policy_decisions
 BEGIN SELECT RAISE(ABORT,'policy decisions are immutable'); END;
CREATE TRIGGER automation_policy_decisions_no_delete BEFORE DELETE ON automation_policy_decisions
 BEGIN SELECT RAISE(ABORT,'policy decisions are immutable'); END;
CREATE TRIGGER automation_control_history_no_update BEFORE UPDATE ON automation_control_history
 BEGIN SELECT RAISE(ABORT,'automation control history is immutable'); END;
CREATE TRIGGER automation_control_history_no_delete BEFORE DELETE ON automation_control_history
 BEGIN SELECT RAISE(ABORT,'automation control history is immutable'); END;
CREATE TRIGGER automation_simulations_no_update BEFORE UPDATE ON automation_simulations
 BEGIN SELECT RAISE(ABORT,'automation simulations are immutable'); END;
CREATE TRIGGER automation_simulations_no_delete BEFORE DELETE ON automation_simulations
 BEGIN SELECT RAISE(ABORT,'automation simulations are immutable'); END;
