CREATE TABLE automation_simulation_requests (
 actor TEXT NOT NULL,
 request_key TEXT NOT NULL,
 request_json TEXT NOT NULL,
 simulation_id TEXT NOT NULL REFERENCES automation_simulations(simulation_id),
 PRIMARY KEY(actor,request_key)
);
CREATE TRIGGER automation_simulation_requests_no_update BEFORE UPDATE ON automation_simulation_requests
 BEGIN SELECT RAISE(ABORT,'simulation requests are immutable'); END;
CREATE TRIGGER automation_simulation_requests_no_delete BEFORE DELETE ON automation_simulation_requests
 BEGIN SELECT RAISE(ABORT,'simulation requests are immutable'); END;
ALTER TABLE automation_policy_decisions ADD COLUMN reviewed_simulation_id TEXT REFERENCES automation_simulations(simulation_id);
