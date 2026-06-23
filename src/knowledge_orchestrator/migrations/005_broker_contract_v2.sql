ALTER TABLE tasks ADD COLUMN broker_task_id TEXT;
ALTER TABLE tasks ADD COLUMN broker_contract_version TEXT NOT NULL DEFAULT '1.0';
ALTER TABLE tasks ADD COLUMN execution_strategy TEXT NOT NULL DEFAULT 'single';
ALTER TABLE tasks ADD COLUMN execution_preset TEXT NOT NULL DEFAULT 'fast';
ALTER TABLE tasks ADD COLUMN selection_mode TEXT NOT NULL DEFAULT 'auto';
ALTER TABLE tasks ADD COLUMN progress_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE tasks ADD COLUMN broker_metadata_json TEXT NOT NULL DEFAULT '{}';

CREATE UNIQUE INDEX idx_tasks_broker_task_id ON tasks(broker_task_id) WHERE broker_task_id IS NOT NULL;
