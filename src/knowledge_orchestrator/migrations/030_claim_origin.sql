-- Apuntes propios publicados tal cual (26-oct-2026).
-- Un apunte que la persona ya trae hecho no pasa por el Broker para resumirse:
-- se publica como está. Sus afirmaciones se siguen extrayendo, pero no tienen
-- otra fuente que el propio apunte, así que se marcan para que pesen menos:
-- no proponen cambios en otras notas y bajan en las búsquedas.
ALTER TABLE knowledge_claims ADD COLUMN claim_origin TEXT NOT NULL DEFAULT 'DOCUMENT'
    CHECK (claim_origin IN ('DOCUMENT', 'OWN_NOTE'));
