-- Repara documentos que «Reintentar» dejó atascados (prueba real, 8-oct-2026).
-- El reintento devolvía la captura a PENDING y los pasos siguientes solo la
-- hacen avanzar desde SUBMITTING/QUEUED: se quedaba «En cola local» aunque su
-- último workflow hubiera terminado. Se le da el estado que habría tenido.
--
-- «Volver a procesar» también pasa por PENDING con un workflow anterior
-- terminado; esos casos se excluyen: su nota fue rechazada, su borrador fue
-- descartado o tienen un reprocesado en marcha.

-- 1) Su último workflow ya está publicado: el documento terminó.
UPDATE captures
SET status = 'COMPLETED',
    archive_path = COALESCE((SELECT n.source_archive_path FROM notes n
                             JOIN workflows w ON w.workflow_id = n.workflow_id
                             WHERE w.capture_id = captures.capture_id AND n.status = 'PUBLISHED'
                             ORDER BY w.revision DESC LIMIT 1), archive_path),
    processing_path = NULL,
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE status IN ('PENDING', 'SUBMITTING', 'QUEUED')
  AND EXISTS (SELECT 1 FROM workflows w JOIN notes n ON n.workflow_id = w.workflow_id
              WHERE w.capture_id = captures.capture_id AND w.status = 'SUCCESS' AND n.status = 'PUBLISHED'
              AND w.revision = (SELECT MAX(x.revision) FROM workflows x WHERE x.capture_id = w.capture_id));

-- 2) Su último workflow terminó en el Broker y aún no tiene nota (p. ej. un
--    borrador por revisar).
UPDATE captures
SET status = 'PROCESSING', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE status IN ('PENDING', 'SUBMITTING', 'QUEUED')
  AND EXISTS (SELECT 1 FROM workflows w
              WHERE w.capture_id = captures.capture_id AND w.status = 'SUCCESS'
              AND COALESCE(w.review_status, '') <> 'REJECTED'
              AND w.revision = (SELECT MAX(x.revision) FROM workflows x WHERE x.capture_id = w.capture_id)
              AND NOT EXISTS (SELECT 1 FROM notes n WHERE n.workflow_id = w.workflow_id))
  AND NOT EXISTS (SELECT 1 FROM reprocess_intents r
                  WHERE r.capture_id = captures.capture_id AND r.status IN ('PREPARED', 'COPIED'));

-- 3) Reintentado y aún en curso: en cola de envío, como lo deja ahora el reintento.
UPDATE captures
SET status = 'SUBMITTING', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE status = 'PENDING'
  AND EXISTS (SELECT 1 FROM workflows w WHERE w.capture_id = captures.capture_id AND w.status = 'RUNNING'
              AND w.revision = (SELECT MAX(x.revision) FROM workflows x WHERE x.capture_id = w.capture_id));
