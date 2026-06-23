ALTER TABLE profiles ADD COLUMN system_prompt TEXT NOT NULL DEFAULT '';
ALTER TABLE profiles ADD COLUMN user_prompt TEXT NOT NULL DEFAULT '';
ALTER TABLE profiles ADD COLUMN chunk_prompt TEXT NOT NULL DEFAULT '';
ALTER TABLE profiles ADD COLUMN synthesis_prompt TEXT NOT NULL DEFAULT '';
ALTER TABLE profiles ADD COLUMN preferred_model TEXT NOT NULL DEFAULT '';
ALTER TABLE profiles ADD COLUMN fallback_allowed INTEGER NOT NULL DEFAULT 1 CHECK (fallback_allowed IN (0, 1));
ALTER TABLE profiles ADD COLUMN temperature REAL NOT NULL DEFAULT 0.3 CHECK (temperature >= 0 AND temperature <= 2);
ALTER TABLE profiles ADD COLUMN max_output_tokens INTEGER NOT NULL DEFAULT 4000 CHECK (max_output_tokens > 0);
ALTER TABLE profiles ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1));
ALTER TABLE profiles ADD COLUMN revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0);

ALTER TABLE topics ADD COLUMN keywords_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE topics ADD COLUMN is_updatable INTEGER NOT NULL DEFAULT 1 CHECK (is_updatable IN (0, 1));
ALTER TABLE topics ADD COLUMN obsolescence_days INTEGER CHECK (obsolescence_days IS NULL OR obsolescence_days >= 0);
ALTER TABLE topics ADD COLUMN auto_review INTEGER NOT NULL DEFAULT 0 CHECK (auto_review IN (0, 1));
ALTER TABLE topics ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1));

ALTER TABLE captures ADD COLUMN source_origin TEXT NOT NULL DEFAULT 'USER_FILE'
    CHECK (source_origin IN ('PLUGIN_CAPTURE', 'USER_FILE', 'OBSIDIAN_NOTE'));
ALTER TABLE captures ADD COLUMN topic_id INTEGER REFERENCES topics(topic_id) ON DELETE SET NULL;
ALTER TABLE captures ADD COLUMN profile_id INTEGER REFERENCES profiles(profile_id) ON DELETE SET NULL;
ALTER TABLE captures ADD COLUMN obsolescence_date TEXT;
ALTER TABLE captures ADD COLUMN domain_enriched_at TEXT;

ALTER TABLE notes ADD COLUMN last_verified_at TEXT;
ALTER TABLE notes ADD COLUMN obsolescence_date TEXT;

CREATE INDEX idx_captures_topic_id ON captures(topic_id);
CREATE INDEX idx_captures_profile_id ON captures(profile_id);
CREATE INDEX idx_captures_domain_pending ON captures(status, domain_enriched_at);

INSERT INTO profiles (
    name,
    config_json,
    system_prompt,
    user_prompt,
    chunk_prompt,
    synthesis_prompt,
    preferred_model,
    fallback_allowed,
    temperature,
    max_output_tokens,
    enabled,
    revision
) VALUES (
    'Técnico Profundo',
    '{}',
    'Eres un analista de conocimiento técnico. Conserva hechos, matices y evidencia de la fuente.',
    'Analiza la fuente titulada {title}.\n\nTranscripción:\n{transcript}',
    'Analiza el fragmento {chunk_index} de {chunk_count} de {title}.\n\n{chunk}',
    'Sintetiza los resultados parciales de {title} sin inventar información.\n\n{partial_results}',
    'llama3.1:8b',
    1,
    0.3,
    4000,
    1,
    1
) ON CONFLICT(name) DO NOTHING;

INSERT INTO topics (
    name,
    position,
    folder,
    config_json,
    default_profile_id,
    keywords_json,
    is_updatable,
    obsolescence_days,
    auto_review,
    enabled
) SELECT
    '_inbox',
    2147483647,
    '_inbox',
    '{}',
    profile_id,
    '[]',
    0,
    NULL,
    0,
    1
FROM profiles
WHERE name = 'Técnico Profundo'
ON CONFLICT(name) DO NOTHING;

UPDATE captures
SET source_origin = 'PLUGIN_CAPTURE'
WHERE source_type = 'youtube' AND metadata_json LIKE '%"plugin_version"%';

UPDATE captures
SET source_origin = 'OBSIDIAN_NOTE'
WHERE source_type = 'obsidian_note';
