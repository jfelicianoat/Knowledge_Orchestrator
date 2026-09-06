-- Adición compatible: status sigue siendo el estado operativo de fase 6.
ALTER TABLE knowledge_claims ADD COLUMN knowledge_state TEXT NOT NULL DEFAULT 'CURRENT'
    CHECK (knowledge_state IN ('CURRENT', 'HISTORICAL', 'SUPERSEDED', 'DISPUTED', 'UNCERTAIN', 'REVIEW_REQUIRED'));
ALTER TABLE knowledge_claims ADD COLUMN valid_from TEXT;
ALTER TABLE knowledge_claims ADD COLUMN valid_until TEXT;
ALTER TABLE knowledge_claims ADD COLUMN superseded_by INTEGER REFERENCES knowledge_claims(claim_id);
ALTER TABLE knowledge_claims ADD COLUMN revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0);

UPDATE knowledge_claims SET
    knowledge_state = CASE status WHEN 'SUPERSEDED' THEN 'SUPERSEDED'
        WHEN 'RETRACTED' THEN 'HISTORICAL' ELSE 'CURRENT' END,
    valid_from = created_at,
    valid_until = CASE WHEN status <> 'ACTIVE' THEN updated_at ELSE NULL END;

UPDATE knowledge_claims SET superseded_by = (
    SELECT new_claim_id FROM update_candidates c WHERE c.target_claim_id = knowledge_claims.claim_id
    AND c.status = 'APPLIED' ORDER BY c.candidate_id DESC LIMIT 1
) WHERE status = 'SUPERSEDED';

CREATE INDEX idx_claims_knowledge_state ON knowledge_claims(knowledge_state, claim_id);
CREATE INDEX idx_claims_successor ON knowledge_claims(superseded_by);

CREATE TABLE knowledge_entities (
    entity_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    entity_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE claim_entities (
    claim_id INTEGER NOT NULL REFERENCES knowledge_claims(claim_id) ON DELETE RESTRICT,
    entity_id INTEGER NOT NULL REFERENCES knowledge_entities(entity_id) ON DELETE RESTRICT,
    PRIMARY KEY (claim_id, entity_id)
);
CREATE INDEX idx_claim_entities_entity ON claim_entities(entity_id, claim_id);

-- Utiliza la misma normalización SQLite que el alta posterior, también para legacy.
INSERT INTO knowledge_entities(name, entity_key)
SELECT min(trim(j.value)), lower(trim(j.value))
FROM knowledge_claims k, json_each(k.entities_json) j
WHERE j.type = 'text' AND length(trim(j.value)) > 0
GROUP BY lower(trim(j.value));
INSERT INTO claim_entities(claim_id, entity_id)
SELECT DISTINCT k.claim_id, e.entity_id
FROM knowledge_claims k, json_each(k.entities_json) j
JOIN knowledge_entities e ON e.entity_key = lower(trim(j.value));

CREATE TABLE claim_state_history (
    history_id INTEGER PRIMARY KEY,
    claim_id INTEGER NOT NULL REFERENCES knowledge_claims(claim_id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    valid_from TEXT,
    valid_until TEXT,
    superseded_by INTEGER REFERENCES knowledge_claims(claim_id) ON DELETE RESTRICT,
    actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    candidate_id INTEGER REFERENCES update_candidates(candidate_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(claim_id, revision)
);
INSERT INTO claim_state_history(claim_id, revision, to_state, valid_from, valid_until, superseded_by, actor, reason)
SELECT claim_id, 1, knowledge_state, valid_from, valid_until, superseded_by, 'migration:012',
    'Estado legacy conservado; fecha de vigencia operativa, no verificación factual'
FROM knowledge_claims;

CREATE TRIGGER claim_history_no_update BEFORE UPDATE ON claim_state_history BEGIN
    SELECT RAISE(ABORT, 'El histórico de claims es inmutable');
END;
CREATE TRIGGER claim_history_no_delete BEFORE DELETE ON claim_state_history BEGIN
    SELECT RAISE(ABORT, 'El histórico de claims es inmutable');
END;

CREATE TABLE knowledge_reconciliation (
    note_id INTEGER PRIMARY KEY REFERENCES notes(note_id) ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK (state IN ('IN_SYNC', 'CONFLICT', 'MISSING')),
    expected_hash TEXT NOT NULL,
    observed_hash TEXT,
    checked_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
