-- Índice de las notas publicadas para recuperar solo lo relevante a una
-- pregunta (21-oct-2026). Antes ChatyGPT mandaba al Broker TODAS las notas en
-- cada pregunta: 89 notas eran ~240k tokens y crecía sin techo. Cada nota se
-- parte en fragmentos que se buscan por palabras (FTS5) y por significado
-- (embeddings calculados por el Broker con un único modelo elegido en Ajustes).

-- El modelo de embeddings del índice. Una sola fila: mezclar vectores de dos
-- modelos da búsquedas basura sin ningún error visible.
CREATE TABLE note_index_config (
    config_id INTEGER PRIMARY KEY CHECK (config_id = 1),
    provider TEXT NOT NULL,
    deployment TEXT NOT NULL,
    model TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Fragmentos de la versión vigente de cada nota. `content_hash` es el de la
-- nota troceada: si la nota cambia, sus fragmentos se rehacen.
CREATE TABLE note_fragments (
    fragment_id INTEGER PRIMARY KEY,
    note_id INTEGER NOT NULL REFERENCES notes(note_id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    heading TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    UNIQUE (note_id, content_hash, ordinal)
);

CREATE INDEX idx_note_fragments_note ON note_fragments(note_id, content_hash);

CREATE VIRTUAL TABLE note_fragments_fts USING fts5(
    text, heading, content='note_fragments', content_rowid='fragment_id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER note_fragments_ai AFTER INSERT ON note_fragments BEGIN
    INSERT INTO note_fragments_fts(rowid, text, heading) VALUES (new.fragment_id, new.text, new.heading);
END;

CREATE TRIGGER note_fragments_ad AFTER DELETE ON note_fragments BEGIN
    INSERT INTO note_fragments_fts(note_fragments_fts, rowid, text, heading)
    VALUES ('delete', old.fragment_id, old.text, old.heading);
END;

-- Vector normalizado (float32) de cada fragmento con el modelo que lo produjo.
-- `model_key` es «proveedor/despliegue/modelo»; `digest`, el del Broker.
CREATE TABLE fragment_embeddings (
    fragment_id INTEGER NOT NULL REFERENCES note_fragments(fragment_id) ON DELETE CASCADE,
    model_key TEXT NOT NULL,
    digest TEXT,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (fragment_id, model_key)
);

-- Un lote de fragmentos enviado al Broker para vectorizarlo.
CREATE TABLE index_jobs (
    job_id TEXT PRIMARY KEY,
    note_id INTEGER NOT NULL REFERENCES notes(note_id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    model_key TEXT NOT NULL,
    fragment_ids_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'READY' CHECK (status IN ('READY', 'QUEUED', 'SUCCESS', 'ERROR')),
    request_json TEXT NOT NULL,
    broker_task_id TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_index_jobs_status ON index_jobs(status, next_retry_at, created_at);

-- Una pregunta que hay que vectorizar antes de buscar. Es durable como
-- `knowledge_queries`: el cliente la crea con Idempotency-Key y la consulta.
CREATE TABLE retrievals (
    retrieval_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    question TEXT NOT NULL,
    model_key TEXT,
    status TEXT NOT NULL DEFAULT 'READY' CHECK (status IN ('READY', 'QUEUED', 'SUCCESS', 'ERROR')),
    request_json TEXT,
    broker_task_id TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    next_retry_at TEXT,
    result_json TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (owner, key_hash)
);

CREATE INDEX idx_retrievals_status ON retrievals(status, next_retry_at, created_at);
