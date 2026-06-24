# Fase 6 — Mantenimiento semántico de Obsidian

## Estado

Implementada y verificada el 2026-06-24. La pantalla de revisión pertenece a la fase 7; la operación de dominio ya exige una llamada explícita a `approve(candidate_id)` y nunca aplica cambios desde el worker.

## Flujo

1. Al publicar una nota se crea idempotentemente un job durable `EXTRACT`.
2. El worker envía al Broker un request v2 `single`, `local_only`, con temperatura cero y JSON Schema estricto.
3. El resultado solo se acepta si cada afirmación cita un `quote` que coincide exactamente con el span de la nota publicada. Los spans de frontmatter se rechazan.
4. Cada claim y su evidencia se guardan en `knowledge_claims` y `evidence_links`.
5. Se recuperan claims anteriores del mismo tema mediante entidades y FTS5. Los embeddings locales son opcionales, tienen umbral de similitud y nunca sustituyen la evidencia.
6. Por cada coincidencia se crea un candidato y un job `COMPARE`. La comparación recibe exclusivamente los dos claims y sus citas locales.
7. `SUPPORTS`, `UNRELATED` y `UNCERTAIN` no generan patch. `EXTENDS`, `CONTRADICTS` y `SUPERSEDES` pueden generar una sustitución y un diff.
8. El worker deja la propuesta en `PENDING_REVIEW`. La nota permanece intacta hasta una aprobación humana explícita.
9. La aprobación guarda la revisión anterior, persiste la intención, escribe un temporal sincronizado y usa `os.replace`. Después actualiza hashes, claims y auditoría.

## Persistencia

La migración `007_semantic_maintenance.sql` añade:

- `knowledge_claims` y su índice FTS5;
- `evidence_links`;
- `claim_embeddings`;
- `update_candidates`;
- `note_revisions`;
- `semantic_jobs`.

Los jobs conservan request, clave idempotente, ID Broker, estado, intento, resultado y error. Un reinicio devuelve `SUBMITTING` a `READY`; un resultado terminal puede procesarse otra vez sin duplicar claims, candidatos ni jobs.

## Reglas de evidencia y seguridad

- Solo se indexan notas con estado `PUBLISHED`.
- Una fecha puede motivar extracción o revisión, pero sin un claim nuevo con span local no se crea una actualización factual.
- Las instrucciones incluidas en las notas se tratan como texto no confiable serializado dentro del prompt.
- Un claim con `manual_lock` no almacena patch y queda rechazado para actualización.
- Antes de aprobar se vuelve a comprobar estado, hash implícito mediante el contenido exacto y el texto del span.
- Si la nota cambió desde el diff, el candidato pasa a `CONFLICT`.
- Rechazar o retirar una nota evita que sus claims se recuperen como evidencia publicada.

## Recuperación

Si el proceso cae después de persistir la intención pero antes de reemplazar la nota, el snapshot permite reconstruir el resultado. Si cae después del reemplazo, el hash final permite completar SQLite sin repetir el cambio. Un contenido distinto de los hashes base y resultado produce `CONFLICT`; nunca se sobrescribe.

## Verificación

La fase añade nueve pruebas específicas: contratos y spans, ciclo automático Broker, FTS5/entidades, embeddings opcionales, evidencia trazable, diff, aprobación humana, `manual_lock`, ausencia de actualizaciones por fecha y recuperación en ambos lados del reemplazo. La suite completa supera 79 pruebas.
