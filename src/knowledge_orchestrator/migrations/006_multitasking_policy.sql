ALTER TABLE profiles ADD COLUMN execution_strategy TEXT NOT NULL DEFAULT 'single'
    CHECK (execution_strategy IN ('single', 'mixture_of_agents'));
ALTER TABLE profiles ADD COLUMN multitasking_steps_json TEXT NOT NULL DEFAULT '["synthesis"]';
ALTER TABLE profiles ADD COLUMN consensus_preset TEXT NOT NULL DEFAULT 'fast'
    CHECK (consensus_preset IN ('fast'));
ALTER TABLE profiles ADD COLUMN consensus_max_proposers INTEGER NOT NULL DEFAULT 3
    CHECK (consensus_max_proposers BETWEEN 2 AND 5);
ALTER TABLE profiles ADD COLUMN consensus_timeout_seconds INTEGER NOT NULL DEFAULT 600
    CHECK (consensus_timeout_seconds BETWEEN 1 AND 3600);
ALTER TABLE profiles ADD COLUMN consensus_fallback_to_single INTEGER NOT NULL DEFAULT 1
    CHECK (consensus_fallback_to_single IN (0, 1));
ALTER TABLE profiles ADD COLUMN cloud_allowed INTEGER NOT NULL DEFAULT 0
    CHECK (cloud_allowed IN (0, 1));
ALTER TABLE profiles ADD COLUMN allowed_providers_json TEXT NOT NULL DEFAULT '["ollama"]';
ALTER TABLE profiles ADD COLUMN data_classification TEXT NOT NULL DEFAULT 'local_only'
    CHECK (data_classification IN ('public', 'internal', 'confidential', 'local_only'));
ALTER TABLE profiles ADD COLUMN max_cost_usd REAL NOT NULL DEFAULT 0.05 CHECK (max_cost_usd >= 0);
ALTER TABLE profiles ADD COLUMN human_review_required INTEGER NOT NULL DEFAULT 0
    CHECK (human_review_required IN (0, 1));

ALTER TABLE tasks ADD COLUMN strategy_fallback_allowed INTEGER NOT NULL DEFAULT 0
    CHECK (strategy_fallback_allowed IN (0, 1));
ALTER TABLE tasks ADD COLUMN replacement_for_task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL;

CREATE INDEX idx_tasks_replacement ON tasks(replacement_for_task_id);
