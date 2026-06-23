# Fase 4 — Publicación y revisión

## Alcance

Esta fase transforma el resultado final validado de un workflow en una nota de Obsidian y conserva la fuente original. También implementa el rechazo reversible y el reprocesado versionado. La interfaz visual para invocar estas operaciones pertenece a la fase 6.

## Publicación durable

El LLM entrega únicamente el cuerpo Markdown. El Orchestrator rechaza resultados vacíos, mayores de 20 MiB, con bytes nulos o con frontmatter propio. Después construye el frontmatter mediante `yaml.safe_dump`, usando exclusivamente metadata persistida de captura, tema, perfil, workflow y revisión.

El protocolo es:

1. Persistir una nota `PUBLISHING` con ruta final, temporal, hash y destino de la fuente.
2. Escribir y sincronizar el temporal dentro de la carpeta temática.
3. Renombrar atómicamente el temporal a la ruta final.
4. Verificar SHA-256 y marcar la nota `PUBLISHED`.
5. Mover la fuente de `processing` a `completed`.
6. Marcar la captura `COMPLETED` únicamente después de ambos efectos.

Los nombres contienen `capture_id` y revisión para evitar sobrescribir otra nota. Los caracteres incompatibles con Windows se eliminan del título.

## Recuperación

Al arrancar se reconcilian:

- notas `PUBLISHING` cuyo temporal o fichero final ya existe;
- notas `PUBLISHED` cuya fuente todavía está en `processing` o ya fue movida;
- rechazos `REJECTING` parcialmente movidos;
- reprocesados `PREPARED` o `COPIED`.

Cada destino se decide antes del efecto externo. Las operaciones se repiten de forma idempotente y el hash impide aceptar una nota distinta de la planificada.

## Rechazo

Una nota publicada puede rechazarse mediante `PublicationService.reject(note_id)`. Primero se persisten los destinos y después:

- la nota sale del vault hacia `rejected/notes`;
- la fuente archivada sale de `completed` hacia `rejected/sources`;
- la nota y la captura quedan `REJECTED`;
- las rutas permanecen en SQLite para auditoría y recuperación.

## Reprocesado

`PublicationService.reprocess(note_id)` solo acepta una nota rechazada cuya fuente siga conservada. Crea una intención durable, copia la evidencia a `processing` y genera un nuevo workflow con revisión creciente. `task_id`, `workflow_id` e `idempotency_key` incluyen esa revisión. La fuente rechazada original no se destruye.

El resultado de la nueva revisión se publica como una nota independiente; la revisión rechazada permanece archivada como evidencia.

## Verificación

Las pruebas cubren publicación y frontmatter, rechazo de frontmatter generado por el LLM, recuperación tras renombrar la nota, recuperación tras mover la fuente, rechazo interrumpido, reprocesado interrumpido y ciclo completo de rechazo → revisión 2 → nueva publicación.
