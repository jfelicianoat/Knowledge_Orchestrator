-- Libera afirmaciones que quedaron «en disputa» tras descartar la contradicción
-- que las marcó (prueba real, 9-oct-2026). Hasta 0.4.1 descartar no deshacía la
-- disputa y quedaban fuera del conocimiento vigente, de las consultas y de las
-- políticas para siempre. Solo se liberan si TODAS las contradicciones que las
-- marcaron fueron descartadas por una persona y no queda ninguna abierta; una
-- disputa puesta a mano (sin propuesta) no se toca.

CREATE TEMP TABLE released_claims AS
SELECT k.claim_id, k.revision
FROM knowledge_claims k
WHERE k.status = 'ACTIVE' AND k.knowledge_state = 'DISPUTED' AND k.manual_lock = 0
  AND EXISTS (SELECT 1 FROM claim_state_history h WHERE h.claim_id = k.claim_id AND h.to_state = 'DISPUTED')
  AND NOT EXISTS (
      SELECT 1 FROM claim_state_history h
      LEFT JOIN update_candidates u ON u.candidate_id = h.candidate_id
      WHERE h.claim_id = k.claim_id AND h.to_state = 'DISPUTED'
        AND (h.candidate_id IS NULL OR u.status <> 'REJECTED' OR COALESCE(u.blocked_reason, '') <> 'HUMAN_REJECTED'))
  AND NOT EXISTS (
      SELECT 1 FROM update_candidates u
      WHERE u.relation = 'CONTRADICTS' AND u.status IN ('PENDING_REVIEW', 'CONFLICT', 'APPLYING')
        AND (u.target_claim_id = k.claim_id OR u.new_claim_id = k.claim_id));

INSERT INTO claim_state_history(claim_id, revision, from_state, to_state, valid_from, actor, reason)
SELECT k.claim_id, k.revision + 1, 'DISPUTED', 'CURRENT', k.valid_from, 'migration:027',
       'Contradicción descartada en la revisión humana'
FROM knowledge_claims k JOIN released_claims r ON r.claim_id = k.claim_id;

UPDATE knowledge_claims
SET knowledge_state = 'CURRENT', revision = revision + 1,
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE claim_id IN (SELECT claim_id FROM released_claims);

DROP TABLE released_claims;
