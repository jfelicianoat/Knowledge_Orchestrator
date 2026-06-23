CREATE TABLE workflows (
    workflow_id TEXT PRIMARY KEY,
    capture_id TEXT NOT NULL REFERENCES captures(capture_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 1,
    profile_id INTEGER NOT NULL REFERENCES profiles(profile_id) ON DELETE RESTRICT,
    profile_revision INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PLANNED', 'RUNNING', 'SUCCESS', 'ERROR', 'CANCELLED')),
    strategy TEXT NOT NULL CHECK (strategy IN ('single', 'chunked')),
    total_steps INTEGER NOT NULL CHECK (total_steps > 0),
    completed_steps INTEGER NOT NULL DEFAULT 0 CHECK (completed_steps >= 0),
    final_result TEXT,
    error_code TEXT,
    error_message TEXT,
    plan_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(capture_id, revision)
);

ALTER TABLE tasks ADD COLUMN step_kind TEXT NOT NULL DEFAULT 'SINGLE'
    CHECK (step_kind IN ('SINGLE', 'CHUNK', 'SYNTHESIS', 'EMBEDDING'));
ALTER TABLE tasks ADD COLUMN sequence_index INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN idempotency_key TEXT;
ALTER TABLE tasks ADD COLUMN request_hash TEXT;
ALTER TABLE tasks ADD COLUMN input_text TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN status_url TEXT;
ALTER TABLE tasks ADD COLUMN cancel_url TEXT;
ALTER TABLE tasks ADD COLUMN result_json TEXT;
ALTER TABLE tasks ADD COLUMN error_code TEXT;
ALTER TABLE tasks ADD COLUMN error_message TEXT;
ALTER TABLE tasks ADD COLUMN error_retryable INTEGER CHECK (error_retryable IN (0, 1));
ALTER TABLE tasks ADD COLUMN next_retry_at TEXT;
ALTER TABLE tasks ADD COLUMN model_used TEXT;
ALTER TABLE tasks ADD COLUMN queued_at TEXT;
ALTER TABLE tasks ADD COLUMN started_at TEXT;
ALTER TABLE tasks ADD COLUMN completed_at TEXT;

CREATE UNIQUE INDEX idx_tasks_idempotency_key ON tasks(idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX idx_tasks_dispatch ON tasks(status, next_retry_at, created_at);
CREATE INDEX idx_tasks_workflow ON tasks(workflow_id, sequence_index);

CREATE TABLE task_dependencies (
    task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    depends_on_task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    PRIMARY KEY(task_id, depends_on_task_id),
    CHECK(task_id <> depends_on_task_id)
);

CREATE TABLE model_catalog (
    name TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'unknown',
    status TEXT NOT NULL,
    context_window INTEGER,
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    discovered_at TEXT NOT NULL,
    PRIMARY KEY(name, provider)
);
