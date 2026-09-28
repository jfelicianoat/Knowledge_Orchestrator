-- Revisión humana del borrador antes de publicarlo (auditoría H01). La casilla
-- «Exigir revisión humana antes de publicar» solo viajaba al Broker como
-- metadata de riesgo: el resultado se publicaba en la bóveda sin que nadie lo
-- viera. La política se congela al planificar, y la aprobación queda ligada al
-- hash del resultado concreto que se revisó.
ALTER TABLE workflows ADD COLUMN review_required INTEGER NOT NULL DEFAULT 0 CHECK (review_required IN (0, 1));
ALTER TABLE workflows ADD COLUMN review_status TEXT CHECK (review_status IN ('PENDING', 'APPROVED', 'REJECTED'));
ALTER TABLE workflows ADD COLUMN review_result_hash TEXT;
ALTER TABLE workflows ADD COLUMN reviewed_at TEXT;

-- Presupuesto por documento (auditoría H08): una bolsa compartida por todas las
-- peticiones del workflow —fragmentos, síntesis, reducciones y reintentos—.
-- NULL = sin límite declarado (perfiles anteriores a esta migración).
ALTER TABLE workflows ADD COLUMN budget_usd REAL CHECK (budget_usd IS NULL OR budget_usd >= 0);
ALTER TABLE workflows ADD COLUMN budget_reserved_usd REAL NOT NULL DEFAULT 0 CHECK (budget_reserved_usd >= 0);
-- Lo reservado por cada petición al enviarla; al terminar se liquida contra el
-- coste real que informa el Broker en `usage`, y la diferencia vuelve a la bolsa.
ALTER TABLE tasks ADD COLUMN budget_reserved_usd REAL NOT NULL DEFAULT 0 CHECK (budget_reserved_usd >= 0);

-- Respaldo de cada afirmación en la fuente original (auditoría H07). La cita de
-- la nota prueba que la afirmación está en el resumen generado, no que la
-- fuente la diga. SOURCE = la aplicación encontró el respaldo en la captura
-- original; MODEL_LINKED = el modelo señaló fragmentos de la fuente que la
-- aplicación no pudo verificar (p. ej. fuente en otro idioma); SUMMARY_ONLY =
-- solo consta en el resumen; UNVERIFIED = afirmaciones anteriores a esta
-- comprobación.
ALTER TABLE knowledge_claims ADD COLUMN source_support TEXT NOT NULL DEFAULT 'UNVERIFIED'
    CHECK (source_support IN ('SOURCE', 'MODEL_LINKED', 'SUMMARY_ONLY', 'UNVERIFIED'));

CREATE TABLE claim_source_evidence (
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id INTEGER NOT NULL REFERENCES knowledge_claims(claim_id) ON DELETE CASCADE,
    capture_id TEXT NOT NULL REFERENCES captures(capture_id) ON DELETE RESTRICT,
    source_sha256 TEXT NOT NULL,
    span_start INTEGER NOT NULL CHECK (span_start >= 0),
    span_end INTEGER NOT NULL CHECK (span_end > span_start),
    quote TEXT NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('LEXICAL', 'MODEL_LINK')),
    score REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(claim_id, span_start, span_end)
);

CREATE INDEX idx_claim_source_evidence_claim ON claim_source_evidence(claim_id);
